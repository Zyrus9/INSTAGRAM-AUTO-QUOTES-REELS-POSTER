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

# Optional but strongly recommended — see README "Openverse authentication"
# section. Without these, Openverse calls go out anonymously, which has been
# unreliable (rate-limited / bot-filtered) in practice.
OPENVERSE_CLIENT_ID = os.environ.get("OPENVERSE_CLIENT_ID", "")
OPENVERSE_CLIENT_SECRET = os.environ.get("OPENVERSE_CLIENT_SECRET", "")

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


def _fetch_fresh_quote(fallback_pool, max_attempts=6):
    """Fetches a random quote from ZenQuotes /random that hasn't been
    posted before (checked against used_history.json). Tries up to
    max_attempts times before giving up and picking an unused fallback,
    or as a last resort any fallback if all are exhausted."""
    for attempt in range(max_attempts):
        try:
            resp = requests.get("https://zenquotes.io/api/random", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                q, a = data[0]["q"].strip(), data[0]["a"].strip()
                if not is_quote_used(q):
                    return q, a
                print(f"[info] Quote already used, retrying ({attempt+1}/{max_attempts})...")
        except Exception as exc:
            print(f"[warn] ZenQuotes /random fetch failed ({exc}); trying fallback.")
            break
    # Try unused fallbacks first
    unused = [p for p in fallback_pool if not is_quote_used(p["q"])]
    pool = unused if unused else fallback_pool
    pick = random.choice(pool)
    return pick["q"], pick["a"]


def fetch_quote():
    """Random unused quote for the picture/quote bot."""
    return _fetch_fresh_quote(FALLBACK_QUOTES)


def fetch_quote_alt():
    """Random unused quote for the video bot (separate call so both bots
    don't burn through retries on the same ZenQuotes session)."""
    return _fetch_fresh_quote(FALLBACK_QUOTES_ALT)


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
            # Prefer photos not seen before; fall back to any if all used
            unused = [p for p in photos if not is_pexels_id_used(p.get("id"))]
            pool = unused if unused else photos
            photo = random.choice(pool)
            src = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("original")
            if not src:
                continue
            img_resp = requests.get(src, timeout=20)
            img_resp.raise_for_status()
            mark_pexels_id_used(photo.get("id"))
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
            # Prefer videos not seen before; fall back to any if all used
            unused = [v for v in candidates if not is_pexels_id_used(v.get("id"))]
            pool = unused if unused else candidates
            video = random.choice(pool)
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
            mark_pexels_id_used(video.get("id"))
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

# Two DIFFERENT wordings of the same "calm nature" vibe — one for the
# picture bot, one for the video bot (mirrors FALLBACK_QUOTES /
# FALLBACK_QUOTES_ALT above). This is the real fix for both bots ending
# up with the same track: they used to search for the identical phrases,
# so if they ran anywhere close together they could easily land on the
# same top result before either had a chance to record it as "used."
# Searching for different words entirely makes that collision extremely
# unlikely regardless of timing, on top of the used_history dedup below.
#
# Kept to 2 words per query on purpose — longer invented phrases (3-4
# words) were tried before and reliably came back with zero results
# once combined with the safe-license filter, even though nothing was
# actually broken. Every word here is drawn from: calm, peaceful, soft,
# soothing, serene, tranquil, ethereal, gentle, quiet, dreamy, tender.
MOOD_QUERIES = [
    "calm ambient",
    "peaceful piano",
    "soothing ambient",
    "serene instrumental",
    "gentle ambient",
    "soft piano",
]

MOOD_QUERIES_ALT = [
    "tranquil ambient",
    "dreamy piano",
    "ethereal ambient",
    "tender piano",
    "quiet ambient",
    "serene piano",
]

# Per-category mood queries, so the track actually matches what's on
# screen (ocean-ish for beach/sea, birdsong-ish for birds, etc.) instead
# of a generic ambient pick every time. Falls back to the matching
# MOOD_QUERIES(_ALT) pool above if a category has no matches on a given
# day. CATEGORY_MOOD_QUERIES is used by the picture bot,
# CATEGORY_MOOD_QUERIES_ALT by the video bot — same categories, worded
# differently, for the same reason as the ALT mood pool above. Same
# 2-word rule as above, for the same reason.
CATEGORY_MOOD_QUERIES = {
    "mountains": ["calm mountain", "peaceful highland", "soothing mountain", "serene peak"],
    "forest": ["calm forest", "peaceful forest", "soothing woods", "gentle forest"],
    "birds": ["calm birdsong", "peaceful birdsong", "soft birdsong", "gentle birds"],
    "beach": ["calm ocean", "peaceful beach", "soothing waves", "serene shoreline"],
    "sea": ["calm sea", "peaceful ocean", "serene sea", "soothing tide"],
}

CATEGORY_MOOD_QUERIES_ALT = {
    "mountains": ["tranquil mountain", "dreamy highland", "ethereal peak", "tender highland"],
    "forest": ["tranquil forest", "dreamy woods", "ethereal forest", "quiet woods"],
    "birds": ["tranquil birdsong", "dreamy birds", "gentle dawn", "soft birds"],
    "beach": ["tranquil shoreline", "dreamy beach", "ethereal coast", "soft shoreline"],
    "sea": ["tranquil ocean", "dreamy sea", "ethereal water", "quiet sea"],
}

# Last-resort tier: single-word, high-frequency terms that are very
# likely to match *something* in Openverse's catalog, tried only after
# every mood/category-specific query above comes back empty. This tier
# trades mood-matching precision for guaranteeing a track gets found.
# Still drawn from the same calm/nature vocabulary, just as single
# words so the search is as broad as possible. Two different wordings
# for the same reason as the pools above: so the two bots still land
# on different tracks if they both fall through to this tier close
# together in time.
BROAD_FALLBACK_QUERIES = ["calm", "peaceful", "soothing", "serene", "gentle", "soft"]
BROAD_FALLBACK_QUERIES_ALT = ["tranquil", "dreamy", "tender", "ethereal", "quiet", "mellow"]

# Only licenses with no NC (non-commercial) or SA/ND (share-alike / no-
# derivatives) restriction — since we trim the track and post it as part
# of a commercial Instagram account. cc0/pdm need no credit; "by" does
# (handled in build_music_credit_line).
SAFE_LICENSES = {"cc0", "pdm", "by"}

_openverse_token_cache = {"token": None}


def _get_openverse_bearer_token(max_attempts=3):
    """Exchanges OPENVERSE_CLIENT_ID/SECRET for a short-lived bearer
    token. Cached for the life of this process (each `prepare` run is a
    fresh process, so no expiry/refresh handling is needed beyond
    that). Returns None if no credentials are configured, or if every
    attempt fails.

    Retries a few times with a longer timeout and short backoff: a
    single slow/timed-out attempt used to fall back to an anonymous
    request immediately, but Openverse now returns a hard 401 for
    anonymous audio searches (it's not just rate-limiting them), so a
    one-off network blip on the token call used to mean the whole
    day's reel came out silent. Retrying here is cheap (this only runs
    once per `prepare` invocation) and turns a transient timeout into
    a non-issue instead of a silent-audio day."""
    if _openverse_token_cache["token"]:
        return _openverse_token_cache["token"]
    if not (OPENVERSE_CLIENT_ID and OPENVERSE_CLIENT_SECRET):
        return None
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(
                f"{OPENVERSE_BASE}/auth_tokens/token/",
                data={
                    "client_id": OPENVERSE_CLIENT_ID,
                    "client_secret": OPENVERSE_CLIENT_SECRET,
                    "grant_type": "client_credentials",
                },
                headers={"User-Agent": "igauto-bot/1.0 (instagram nature-quote reel bot)"},
                timeout=30,
            )
            resp.raise_for_status()
            token = resp.json().get("access_token")
            _openverse_token_cache["token"] = token
            return token
        except Exception as exc:
            last_exc = exc
            print(f"[warn] Openverse token request failed on attempt {attempt}/{max_attempts} ({exc}).")
            if attempt < max_attempts:
                time.sleep(3 * attempt)
    print(f"[warn] Could not get an Openverse access token after {max_attempts} attempts "
          f"({last_exc}); trying anonymous instead (may fail — Openverse now rejects "
          f"anonymous audio search outright).")
    return None


def _openverse_track_identifier(track):
    """A stable-ish key for a track, used for dedup history. Prefer
    Openverse's own id; fall back to the audio URL, then title+creator,
    so dedup still works even if a field is occasionally missing."""
    return str(
        track.get("id")
        or track.get("url")
        or f"{track.get('title')}|{track.get('creator')}"
    )


def fetch_openverse_track(duration_needed, category=None, alt=False):
    """Finds a calm/ambient CC0, Public-Domain, or plain-Attribution
    track via Openverse, downloads the audio, and returns a dict:
    {name, artist_name, license, needs_credit, local_path}. Returns None
    only if every mood query comes back completely empty (rare) —
    callers must still handle a silent reel gracefully in that case.

    If `category` is given (one of NATURE_CATEGORIES' keys), tries mood
    queries themed to that category first — so a beach clip is more
    likely to get an ocean-ish track instead of generic piano — before
    falling back to the generic mood pool. Every query in the combined
    pool is tried (not just the first few), so a couple of empty/failed
    lookups on a given day don't leave the reel silent. Each result page
    is also filtered down to tracks not already used recently, so the
    same track doesn't keep showing up post after post.

    Pass `alt=True` (the video bot does this) to search with the ALT
    query wording instead of the picture bot's — different words means
    a different results list, so the two bots land on different tracks
    even if they happen to run close together, before either has
    recorded its pick in used_history.json."""
    category_pool = CATEGORY_MOOD_QUERIES_ALT if alt else CATEGORY_MOOD_QUERIES
    generic_pool = MOOD_QUERIES_ALT if alt else MOOD_QUERIES
    broad_pool = BROAD_FALLBACK_QUERIES_ALT if alt else BROAD_FALLBACK_QUERIES
    queries_to_try = list(category_pool.get(category, [])) if category else []
    remaining_generic = [q for q in generic_pool if q not in queries_to_try]
    random.shuffle(remaining_generic)
    queries_to_try += remaining_generic
    queries_to_try += [q for q in broad_pool if q not in queries_to_try]
    needed_ms = duration_needed * 1000

    headers = {"User-Agent": "igauto-bot/1.0 (instagram nature-quote reel bot)"}
    token = _get_openverse_bearer_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        print("[warn] No OPENVERSE_CLIENT_ID/SECRET configured (or token exchange failed); "
              "calling Openverse anonymously, which may be rate-limited or blocked.")

    for query in queries_to_try:
        try:
            resp = requests.get(
                f"{OPENVERSE_BASE}/audio/",
                params={
                    "q": query,
                    "license": ",".join(sorted(SAFE_LICENSES)),
                    "category": "music",
                    "page_size": 40,
                },
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            candidates = [t for t in results if (t.get("duration") or 0) >= needed_ms]
            if not candidates:
                candidates = results
            if not candidates:
                continue
            # Prefer a track we haven't posted recently; only reuse one
            # if literally every candidate on this page has already
            # been used (still better than a silent reel).
            unused = [t for t in candidates if not is_audio_used(_openverse_track_identifier(t))]
            pool = unused if unused else candidates
            track = random.choice(pool)
            audio_url = track.get("url")
            if not audio_url:
                continue
            audio_resp = requests.get(audio_url, timeout=30)
            audio_resp.raise_for_status()
            raw_path = os.path.join(REPO_ROOT, ".tmp_audio_raw.mp3")
            with open(raw_path, "wb") as f:
                f.write(audio_resp.content)
            mark_audio_used(_openverse_track_identifier(track))
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
    print("[warn] No Openverse tracks matched after trying every mood query; reel will have no background music.")
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


# --------------------------------------------------------------------------
# Used-content history — persisted as posts/used_history.json in the repo
# so the bot never repeats a quote or a photo/video across days.
# --------------------------------------------------------------------------

USED_HISTORY_PATH = os.path.join(POSTS_DIR, "used_history.json")
_MAX_QUOTE_HISTORY = 200   # forget quotes older than this so the pool never drains
_MAX_MEDIA_HISTORY = 500   # same for photo/video Pexels IDs
_MAX_AUDIO_HISTORY = 120   # same idea for Openverse tracks — ~a couple months before repeats


def _load_history():
    h = {"quotes": [], "pexels_ids": [], "audio_tracks": []}
    if os.path.exists(USED_HISTORY_PATH):
        try:
            with open(USED_HISTORY_PATH) as f:
                loaded = json.load(f)
            h.update(loaded)
        except Exception:
            pass
    # Old history files (from before audio dedup existed) won't have this
    # key — make sure it's always present so callers can rely on it.
    h.setdefault("audio_tracks", [])
    return h


def _save_history(h):
    os.makedirs(POSTS_DIR, exist_ok=True)
    with open(USED_HISTORY_PATH, "w") as f:
        json.dump(h, f, indent=2)


def mark_quote_used(quote_text):
    h = _load_history()
    key = quote_text.strip().lower()
    if key not in h["quotes"]:
        h["quotes"].append(key)
    h["quotes"] = h["quotes"][-_MAX_QUOTE_HISTORY:]
    _save_history(h)


def is_quote_used(quote_text):
    h = _load_history()
    return quote_text.strip().lower() in h["quotes"]


def mark_pexels_id_used(pexels_id):
    h = _load_history()
    pid = str(pexels_id)
    if pid not in h["pexels_ids"]:
        h["pexels_ids"].append(pid)
    h["pexels_ids"] = h["pexels_ids"][-_MAX_MEDIA_HISTORY:]
    _save_history(h)


def is_pexels_id_used(pexels_id):
    h = _load_history()
    return str(pexels_id) in h["pexels_ids"]


def mark_audio_used(track_identifier):
    h = _load_history()
    key = str(track_identifier)
    if key not in h["audio_tracks"]:
        h["audio_tracks"].append(key)
    h["audio_tracks"] = h["audio_tracks"][-_MAX_AUDIO_HISTORY:]
    _save_history(h)


def is_audio_used(track_identifier):
    h = _load_history()
    return str(track_identifier) in h["audio_tracks"]


def cleanup_temp_files():
    for name in (".tmp_clip_source.mp4", ".tmp_audio_raw.mp3"):
        path = os.path.join(REPO_ROOT, name)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
