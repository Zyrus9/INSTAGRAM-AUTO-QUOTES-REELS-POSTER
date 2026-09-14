"""
common.py — shared engine for both bots in this repo:
    bot_picture.py  -> nature photo + quote, animated into a Reel
    bot_video.py    -> real nature video clip + quote, posted as a Reel

Holds everything that isn't specific to "still photo" vs "video clip":
quote fetching, nature-themed media search terms, hashtag + caption
generation, Openverse background music, ffmpeg helpers, and Instagram
Reels publishing (Graph API).
"""

import os
import io
import sys
import json
import time
import random
import subprocess
import datetime as dt

import requests
from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# Config / secrets (read from environment — set as GitHub Actions secrets)
# --------------------------------------------------------------------------

IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
IG_HANDLE = os.environ.get("IG_HANDLE") or "fragmentfiles"
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")  # "owner/repo", auto-set in Actions
GITHUB_REF_NAME = os.environ.get("GITHUB_REF_NAME", "main")  # branch, auto-set in Actions

GRAPH_API_VERSION = "v22.0"
GRAPH_HOST = "https://graph.instagram.com"

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
FONT_CACHE_DIR = os.path.join(REPO_ROOT, "fonts")
POSTS_DIR = os.path.join(REPO_ROOT, "posts")

REEL_SIZE = (1080, 1920)  # 9:16 — Instagram Reels

# --------------------------------------------------------------------------
# Quotes
# --------------------------------------------------------------------------

FALLBACK_QUOTES = [
    {"q": "The way to get started is to quit talking and begin doing.", "a": "Walt Disney"},
    {"q": "Life is what happens when you're busy making other plans.", "a": "John Lennon"},
    {"q": "The future belongs to those who believe in the beauty of their dreams.", "a": "Eleanor Roosevelt"},
    {"q": "It does not matter how slowly you go as long as you do not stop.", "a": "Confucius"},
    {"q": "Everything you've ever wanted is on the other side of fear.", "a": "George Addair"},
    {"q": "Success is not final, failure is not fatal: it is the courage to continue that counts.", "a": "Winston Churchill"},
    {"q": "Believe you can and you're halfway there.", "a": "Theodore Roosevelt"},
    {"q": "Almost everything will work again if you unplug it for a few minutes, including you.", "a": "Anne Lamott"},
    {"q": "Peace comes from within. Do not seek it without.", "a": "Buddha"},
    {"q": "Adopt the pace of nature: her secret is patience.", "a": "Ralph Waldo Emerson"},
]

FALLBACK_QUOTES_ALT = [
    {"q": "In the middle of every difficulty lies opportunity.", "a": "Albert Einstein"},
    {"q": "The quieter you become, the more you can hear.", "a": "Ram Dass"},
    {"q": "Nature does not hurry, yet everything is accomplished.", "a": "Lao Tzu"},
    {"q": "Slow down and everything you are chasing will come around and catch you.", "a": "John De Paola"},
    {"q": "Wherever you are, be all there.", "a": "Jim Elliot"},
    {"q": "Not all those who wander are lost.", "a": "J.R.R. Tolkien"},
    {"q": "The best time to plant a tree was 20 years ago. The second best time is now.", "a": "Chinese Proverb"},
    {"q": "Every morning is a chance to begin again.", "a": "Anonymous"},
]


def fetch_quote():
    """Today's quote from ZenQuotes (free, no key). Falls back to a local
    list if the API is unreachable or rate-limited."""
    try:
        resp = requests.get("https://zenquotes.io/api/today", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            return data[0]["q"].strip(), data[0]["a"].strip()
    except Exception as exc:
        print(f"[warn] ZenQuotes /today fetch failed ({exc}); using fallback quote.")
    pick = random.choice(FALLBACK_QUOTES)
    return pick["q"], pick["a"]


def fetch_quote_alt():
    """A different quote for the second bot, so both bots don't post the
    identical quote on the same day. ZenQuotes' /random endpoint (free,
    no key) with its own separate fallback list."""
    try:
        resp = requests.get("https://zenquotes.io/api/random", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            return data[0]["q"].strip(), data[0]["a"].strip()
    except Exception as exc:
        print(f"[warn] ZenQuotes /random fetch failed ({exc}); using fallback quote.")
    pick = random.choice(FALLBACK_QUOTES_ALT)
    return pick["q"], pick["a"]


# --------------------------------------------------------------------------
# Nature themes — used for both photo search (bot_picture) and video
# search (bot_video), plus hashtags
# --------------------------------------------------------------------------

NATURE_CATEGORIES = {
    "mountains": {
        "photo_queries": ["misty mountain sunrise", "mountain peak clouds", "snow capped mountain range", "mountain valley aerial"],
        "video_queries": ["mountain sunrise clouds", "misty mountains drone", "mountain range aerial"],
        "hashtags": ["mountainview", "naturelovers", "calmvibes"],
    },
    "forest": {
        "photo_queries": ["sunlight forest path", "tall trees canopy", "misty forest morning", "green forest path"],
        "video_queries": ["forest sunlight trees", "misty forest morning", "walking forest path"],
        "hashtags": ["forestbathing", "intothewoods", "naturetherapy"],
    },
    "birds": {
        "photo_queries": ["birds flying sunset sky", "flock of birds silhouette", "bird sky golden hour"],
        "video_queries": ["birds flying sky", "flock of birds sunset", "birds silhouette flying"],
        "hashtags": ["birdsinflight", "naturemoments", "skyview"],
    },
    "beach": {
        "photo_queries": ["tropical beach aerial", "beach waves sunset", "sandy beach shoreline"],
        "video_queries": ["beach waves aerial", "tropical beach drone", "waves shoreline sunset"],
        "hashtags": ["beachvibes", "oceanview", "saltlife"],
    },
    "sea": {
        "photo_queries": ["calm sea horizon", "ocean waves aerial", "ocean sunrise reflection"],
        "video_queries": ["ocean waves aerial", "calm sea horizon", "ocean sunrise slow motion"],
        "hashtags": ["oceanlovers", "seaside", "blueplanet"],
    },
}

GENERIC_HASHTAGS = [
    "quoteoftheday",
    "dailyquote",
    "naturequotes",
    "calmvibes",
    "peacefulmind",
    "slowliving",
]


def pick_nature_category():
    return random.choice(list(NATURE_CATEGORIES.keys()))


def build_hashtags(category, author):
    tags = list(GENERIC_HASHTAGS)
    tags += NATURE_CATEGORIES.get(category, {}).get("hashtags", [])
    author_tag = "".join(w.capitalize() for w in author.replace(".", "").split())
    if author_tag:
        tags.append(f"{author_tag}Quotes")
    seen, ordered = set(), []
    for t in tags:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(t)
    return ordered[:15]


# --------------------------------------------------------------------------
# Caption generator
# --------------------------------------------------------------------------
# The old bot just reposted the raw quote text as the caption. This builds
# an actual caption: a rotating "hook" line, the quote block, an optional
# music-credit line, then hashtags.

CAPTION_HOOKS = [
    "A gentle reminder for today 🌿",
    "Read this one slowly. 🤍",
    "Save this for a day you need it. 📌",
    "Something to sit with for a moment.",
    "This is worth a second read.",
    "For whoever needed to hear this today ✨",
    "Slow down and read this twice.",
    "Let this one sink in.",
    "A small pause, before you keep going.",
    "Carry this with you today.",
]


def build_music_credit_line(track):
    """track is a dict from fetch_openverse_track(), or None if no track
    was available (in which case no credit line is needed)."""
    if not track:
        return None
    if track["needs_credit"]:
        return f"🎵 \"{track['name']}\" — {track['artist_name']} (CC BY, via Openverse)"
    return f"🎵 \"{track['name']}\" — {track['artist_name']} (Public Domain, via Openverse)"


def build_caption(quote, author, hashtags, music_credit_line=None):
    hook = random.choice(CAPTION_HOOKS)
    tag_line = " ".join(f"#{t}" for t in hashtags)
    parts = [hook, "", f'"{quote}"', f"— {author}"]
    if music_credit_line:
        parts += ["", music_credit_line]
    parts += ["", tag_line]
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------

GOOGLE_FONT_URLS = {
    "regular": "https://raw.githubusercontent.com/google/fonts/main/ofl/lora/Lora%5Bwght%5D.ttf",
    "italic": "https://raw.githubusercontent.com/google/fonts/main/ofl/lora/Lora-Italic%5Bwght%5D.ttf",
}

SYSTEM_FONT_FALLBACKS = {
    "regular": "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "italic": "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
}


def _download_font(url, dest_path):
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(resp.content)


def get_font_path(style):
    """Returns a filesystem path to a usable .ttf (downloads + caches a
    Google Font, falls back to a system font). Returned as a path (not a
    loaded ImageFont) because ffmpeg's drawtext also needs a path."""
    os.makedirs(FONT_CACHE_DIR, exist_ok=True)
    cached_path = os.path.join(FONT_CACHE_DIR, f"Lora-{style}.ttf")
    if not os.path.exists(cached_path):
        try:
            _download_font(GOOGLE_FONT_URLS[style], cached_path)
        except Exception as exc:
            print(f"[warn] Could not download font ({exc}); trying system font.")
    if os.path.exists(cached_path):
        return cached_path
    fallback_path = SYSTEM_FONT_FALLBACKS.get(style)
    if fallback_path and os.path.exists(fallback_path):
        return fallback_path
    return None


def get_font(style, size):
    path = get_font_path(style)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    print("[warn] Falling back to PIL default bitmap font (low quality).")
    return ImageFont.load_default()


# --------------------------------------------------------------------------
# Watermark — stamped onto the final rendered video (after any zoom/crop)
# so it always sits in the same fixed spot on screen, on both bots.
# --------------------------------------------------------------------------

def _escape_drawtext_literal(text):
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def build_watermark_drawtext_filter():
    """Returns an ffmpeg drawtext filter chunk (no leading/trailing comma)
    that stamps the IG_HANDLE watermark near the bottom-center of the
    frame. Apply this LAST in a filter chain, after any scale/zoom/crop,
    so the watermark's screen position never shifts or gets cropped."""
    font_path = get_font_path("regular") or SYSTEM_FONT_FALLBACKS["regular"]
    watermark_text = _escape_drawtext_literal(IG_HANDLE)
    return (
        f"drawtext=text='{watermark_text}':fontfile={font_path}:fontsize=30:"
        f"fontcolor=white@0.85:x=(w-text_w)/2:y=h-80:"
        f"shadowcolor=black@0.6:shadowx=1:shadowy=1"
    )


# --------------------------------------------------------------------------
# Pexels: photos + videos
# --------------------------------------------------------------------------

def fetch_nature_photo(category):
    """Real nature photo from Pexels for the given category. Returns a
    PIL Image, or None if unavailable (caller falls back to a gradient)."""
    if not PEXELS_API_KEY:
        print("[warn] No PEXELS_API_KEY set; using gradient background.")
        return None
    queries = list(NATURE_CATEGORIES[category]["photo_queries"])
    random.shuffle(queries)
    for query in queries:
        try:
            resp = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": query, "orientation": "portrait", "per_page": 15},
                timeout=15,
            )
            resp.raise_for_status()
            photos = resp.json().get("photos", [])
            if not photos:
                continue
            photo = random.choice(photos)
            src = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("original")
            if not src:
                continue
            img_resp = requests.get(src, timeout=20)
            img_resp.raise_for_status()
            return Image.open(io.BytesIO(img_resp.content)).convert("RGB")
        except Exception as exc:
            print(f"[warn] Pexels photo fetch failed for query {query!r}: {exc}")
            continue
    print("[warn] All Pexels photo attempts failed; using gradient background.")
    return None


def fetch_nature_video(category, min_duration=6, max_duration=40):
    """Real nature video clip from Pexels for the given category.
    Downloads it to a local temp path and returns that path, or None."""
    if not PEXELS_API_KEY:
        print("[warn] No PEXELS_API_KEY set; cannot fetch a video clip.")
        return None
    queries = list(NATURE_CATEGORIES[category]["video_queries"])
    random.shuffle(queries)
    for query in queries:
        try:
            resp = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": query, "orientation": "portrait", "per_page": 15},
                timeout=15,
            )
            resp.raise_for_status()
            videos = resp.json().get("videos", [])
            candidates = [v for v in videos if min_duration <= v.get("duration", 0) <= max_duration]
            if not candidates:
                candidates = videos
            if not candidates:
                continue
            video = random.choice(candidates)
            files = sorted(
                [f for f in video.get("video_files", []) if f.get("width") and f.get("height")],
                key=lambda f: f["width"] * f["height"],
            )
            # Prefer a portrait-ish file around HD resolution — smallest
            # file that's still at least 720p tall, else the largest available.
            pick = next((f for f in files if f["height"] >= 1280), files[-1] if files else None)
            if not pick:
                continue
            video_resp = requests.get(pick["link"], timeout=60)
            video_resp.raise_for_status()
            tmp_path = os.path.join(REPO_ROOT, ".tmp_clip_source.mp4")
            with open(tmp_path, "wb") as f:
                f.write(video_resp.content)
            return tmp_path
        except Exception as exc:
            print(f"[warn] Pexels video fetch failed for query {query!r}: {exc}")
            continue
    print("[warn] All Pexels video attempts failed.")
    return None


# --------------------------------------------------------------------------
# Openverse: royalty-free background music (Creative Commons search engine
# run by the WordPress Foundation — aggregates Jamendo, ccMixter, Free
# Music Archive, etc. No signup, no API key, free to use.)
# --------------------------------------------------------------------------

OPENVERSE_BASE = "https://api.openverse.org/v1"
MOOD_QUERIES = [
    "calm ambient nature",
    "peaceful piano meditation",
    "relaxing ambient chill",
    "soft acoustic calm",
    "gentle ambient instrumental",
]

# Per-category mood queries, so the track actually matches what's on
# screen (ocean-ish for beach/sea, birdsong-ish for birds, etc.) instead
# of a generic ambient pick every time. Falls back to MOOD_QUERIES above
# if a category has no matches on a given day.
CATEGORY_MOOD_QUERIES = {
    "mountains": ["epic calm ambient", "mountain ambient calm", "peaceful piano meditation", "gentle ambient instrumental"],
    "forest": ["forest ambient calm", "soft acoustic calm", "gentle ambient instrumental", "calm ambient nature"],
    "birds": ["birdsong ambient", "gentle acoustic morning", "peaceful piano meditation", "calm ambient nature"],
    "beach": ["ocean waves ambient", "tropical chill ambient", "relaxing ambient chill", "calm ambient nature"],
    "sea": ["ocean waves ambient", "calm ambient nature", "relaxing ambient chill", "soft acoustic calm"],
}

# Only licenses with no NC (non-commercial) or SA/ND (share-alike / no-
# derivatives) restriction — since we trim the track and post it as part
# of a commercial Instagram account. cc0/pdm need no credit; "by" does
# (handled in build_music_credit_line).
SAFE_LICENSES = {"cc0", "pdm", "by"}


def fetch_openverse_track(duration_needed, category=None):
    """Finds a calm/ambient CC0, Public-Domain, or plain-Attribution
    track via Openverse, downloads the audio, and returns a dict:
    {name, artist_name, license, needs_credit, local_path}. Returns None
    if nothing suitable is found — callers must handle a silent (no-
    audio) reel gracefully in that case.

    If `category` is given (one of NATURE_CATEGORIES' keys), tries a
    handful of mood queries themed to that category first — so a beach
    clip is more likely to get an ocean-ish track instead of generic
    piano — before falling back to the generic mood pool."""
    queries_to_try = list(CATEGORY_MOOD_QUERIES.get(category, [])) if category else []
    remaining_generic = [q for q in MOOD_QUERIES if q not in queries_to_try]
    random.shuffle(remaining_generic)
    queries_to_try += remaining_generic
    needed_ms = duration_needed * 1000

    for query in queries_to_try[:4]:
        try:
            resp = requests.get(
                f"{OPENVERSE_BASE}/audio/",
                params={
                    "q": query,
                    "license": ",".join(sorted(SAFE_LICENSES)),
                    "category": "music",
                    "page_size": 20,
                },
                headers={"User-Agent": "igauto-bot/1.0 (instagram nature-quote reel bot)"},
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            candidates = [t for t in results if (t.get("duration") or 0) >= needed_ms]
            if not candidates:
                candidates = results
            if not candidates:
                continue
            track = random.choice(candidates)
            audio_url = track.get("url")
            if not audio_url:
                continue
            audio_resp = requests.get(audio_url, timeout=30)
            audio_resp.raise_for_status()
            raw_path = os.path.join(REPO_ROOT, ".tmp_audio_raw.mp3")
            with open(raw_path, "wb") as f:
                f.write(audio_resp.content)
            license_slug = (track.get("license") or "").lower()
            return {
                "name": track.get("title") or "Untitled",
                "artist_name": track.get("creator") or "Unknown Artist",
                "license": license_slug,
                "needs_credit": license_slug not in ("cc0", "pdm"),
                "local_path": raw_path,
            }
        except Exception as exc:
            print(f"[warn] Openverse fetch failed for query {query!r} ({exc}); trying next mood.")
            continue
    print("[warn] No Openverse tracks matched; reel will have no background music.")
    return None


def prepare_audio_clip(input_path, duration, out_path):
    """Trims/pads background music to exactly `duration` seconds with a
    1s fade-in and fade-out, re-encoded as AAC-friendly stereo mp3."""
    fade_out_start = max(duration - 1.5, 0)
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-t", str(duration),
        "-af", f"afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out_start}:d=1.5",
        "-ar", "44100", "-ac", "2",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


# --------------------------------------------------------------------------
# Public media URL (hosted via this GitHub repo — Instagram's API needs a
# public URL, so we commit the rendered file and use its raw GitHub URL)
# --------------------------------------------------------------------------

def build_public_media_url(subfolder, date_str, filename):
    if not GITHUB_REPOSITORY:
        raise EnvironmentError(
            "GITHUB_REPOSITORY is not set. This should be run inside GitHub "
            "Actions, or set it manually as 'owner/repo' for local testing."
        )
    return (
        f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/"
        f"{GITHUB_REF_NAME}/posts/{subfolder}/{date_str}/{filename}"
    )


# --------------------------------------------------------------------------
# Instagram Reels publishing (Graph API)
# --------------------------------------------------------------------------

def create_reels_container(video_url, caption):
    url = f"{GRAPH_HOST}/{GRAPH_API_VERSION}/{IG_USER_ID}/media"
    resp = requests.post(
        url,
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true",
            "access_token": IG_ACCESS_TOKEN,
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"[error] Instagram container creation failed {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    return resp.json()["id"]


def wait_for_container_ready(container_id, timeout=280, interval=10):
    """Video containers take longer to process than image containers."""
    url = f"{GRAPH_HOST}/{container_id}"
    waited = 0
    while waited < timeout:
        resp = requests.get(
            url, params={"fields": "status_code", "access_token": IG_ACCESS_TOKEN}, timeout=15
        )
        resp.raise_for_status()
        status = resp.json().get("status_code")
        if status == "FINISHED":
            return True
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Container failed with status: {status}")
        time.sleep(interval)
        waited += interval
    raise TimeoutError("Timed out waiting for media container to finish processing.")


def publish_container(creation_id):
    url = f"{GRAPH_HOST}/{GRAPH_API_VERSION}/{IG_USER_ID}/media_publish"
    resp = requests.post(
        url, data={"creation_id": creation_id, "access_token": IG_ACCESS_TOKEN}, timeout=30
    )
    resp.raise_for_status()
    return resp.json()["id"]


# --------------------------------------------------------------------------
# Local record-keeping
# --------------------------------------------------------------------------

def save_record(subfolder, date_str, record_updates, media_id=None):
    day_dir = os.path.join(POSTS_DIR, subfolder, date_str)
    os.makedirs(day_dir, exist_ok=True)
    record_path = os.path.join(day_dir, "record.json")
    record = {}
    if os.path.exists(record_path):
        with open(record_path) as f:
            record = json.load(f)
    record.update(record_updates)
    record["dry_run"] = DRY_RUN
    if media_id is not None:
        record["instagram_media_id"] = media_id
    with open(record_path, "w") as f:
        json.dump(record, f, indent=2)
    return record


def load_record(subfolder, date_str):
    record_path = os.path.join(POSTS_DIR, subfolder, date_str, "record.json")
    with open(record_path) as f:
        return json.load(f)


def cleanup_temp_files():
    for name in (".tmp_clip_source.mp4", ".tmp_audio_raw.mp3"):
        path = os.path.join(REPO_ROOT, name)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
