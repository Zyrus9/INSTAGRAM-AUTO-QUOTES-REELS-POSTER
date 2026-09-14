"""
Picture Bot — Nature Quote Reel
--------------------------------
Fetches a daily quote, picks a peaceful nature scene (mountains, forest,
birds, beach, or sea) from Pexels, renders the quote over it, then
animates that still image into a slow Ken-Burns-style zoom/pan video
with Creative-Commons background music — and posts it as an Instagram
Reel via the Graph API.

Two phases (see bottom of file), same pattern as before: prepare writes
posts/picture/<date>/, the workflow commits + pushes it (so the raw
GitHub URL is public), then publish reads that record and posts to IG.

Environment variables — see README.md for the full list.

Usage:
    python bot_picture.py prepare
    python bot_picture.py publish
"""

import os
import sys
import random
import subprocess
import datetime as dt

from PIL import Image, ImageDraw

import common

REEL_DURATION = 8  # seconds
REEL_FPS = 30


# --------------------------------------------------------------------------
# Still image (quote over nature photo) — mostly unchanged from the
# original bot, just re-sized to 9:16 for Reels instead of 4:5 for feed.
# --------------------------------------------------------------------------

def cover_crop(img, size):
    target_w, target_h = size
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w, new_h = int(src_w * scale) + 1, int(src_h * scale) + 1
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def draw_text_with_shadow(draw, xy, text, font, fill, shadow_fill=(0, 0, 0, 200), offset=3):
    """Drop-shadow instead of a background box — keeps text readable on
    any photo without a hard-edged dark rectangle behind it."""
    x, y = xy
    draw.text((x + offset, y + offset), text, font=font, fill=shadow_fill)
    draw.text((x, y), text, font=font, fill=fill)


NATURE_GRADIENTS = [
    ((15, 35, 30), (60, 110, 90)),   # forest green dusk
    ((20, 30, 55), (70, 110, 150)),  # dawn sky blue
    ((30, 25, 45), (140, 90, 90)),   # mountain sunrise
    ((10, 30, 40), (30, 90, 100)),   # deep sea teal
]


def make_gradient_background(size):
    top, bottom = random.choice(NATURE_GRADIENTS)
    w, h = size
    base = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(base)
    for y in range(h):
        ratio = y / h
        r = int(top[0] + (bottom[0] - top[0]) * ratio)
        g = int(top[1] + (bottom[1] - top[1]) * ratio)
        b = int(top[2] + (bottom[2] - top[2]) * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return base


def wrap_text_to_width(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_quote_image(quote, author, category, out_path):
    w, h = common.REEL_SIZE
    photo = common.fetch_nature_photo(category)
    base = cover_crop(photo, common.REEL_SIZE) if photo is not None else make_gradient_background(common.REEL_SIZE)

    img = base.convert("RGBA")
    overall_dim = Image.new("RGBA", (w, h), (0, 0, 0, 60))
    img = Image.alpha_composite(img, overall_dim)

    draw = ImageDraw.Draw(img)
    margin = 110
    max_text_width = w - 2 * margin

    quote_font_size = 62
    quote_font = common.get_font("regular", quote_font_size)
    lines = wrap_text_to_width(draw, quote, quote_font, max_text_width)
    while len(lines) > 8 and quote_font_size > 34:
        quote_font_size -= 4
        quote_font = common.get_font("regular", quote_font_size)
        lines = wrap_text_to_width(draw, quote, quote_font, max_text_width)

    line_height = int(quote_font_size * 1.45)
    total_text_height = line_height * len(lines)
    author_font = common.get_font("italic", 34)

    author_text = f"— {author}"
    author_gap = 34
    author_height = author_font.getbbox(author_text)[3]
    block_height = total_text_height + author_gap + author_height
    y = (h - block_height) / 2

    # No background box behind the text — a drop shadow keeps it readable
    # on any photo without leaving a hard-edged dark patch on the frame.
    for line in lines:
        line_width = draw.textlength(line, font=quote_font)
        x = (w - line_width) / 2
        draw_text_with_shadow(draw, (x, y), line, quote_font, "white")
        y += line_height

    author_width = draw.textlength(author_text, font=author_font)
    draw_text_with_shadow(
        draw, ((w - author_width) / 2, y + author_gap), author_text, author_font, (235, 235, 235)
    )

    # Note: the "fragmentfiles" watermark is stamped onto the final video
    # in render_ken_burns_reel() instead of here — that way it stays
    # fixed at the bottom of the frame instead of drifting/getting
    # cropped as the Ken Burns zoom moves in.

    img.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path


# --------------------------------------------------------------------------
# Ken Burns animation + audio mux
# --------------------------------------------------------------------------

def render_ken_burns_reel(still_image_path, audio_path, out_path, duration=REEL_DURATION, fps=REEL_FPS):
    """Animates a slow zoom on the still image and muxes in background
    audio (if any). Produces a vertical 1080x1920 mp4."""
    w, h = common.REEL_SIZE
    frames = duration * fps
    zoom_expr = f"min(zoom+{0.15 / frames:.6f},1.15)"

    filter_complex = (
        f"[0:v]scale=-2:{h * 2},"
        f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={w}x{h}:fps={fps},"
        f"format=yuv420p,"
        f"{common.build_watermark_drawtext_filter()}[v]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", still_image_path,
    ]
    if audio_path:
        cmd += ["-i", audio_path]
    cmd += ["-filter_complex", filter_complex, "-map", "[v]"]
    if audio_path:
        cmd += ["-map", "1:a", "-c:a", "aac", "-shortest"]
    cmd += [
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def cmd_prepare():
    today = dt.date.today().isoformat()
    print(f"[info] Preparing picture-bot reel for {today} (DRY_RUN={common.DRY_RUN})")

    quote, author = common.fetch_quote()
    common.mark_quote_used(quote)
    category = common.pick_nature_category()
    hashtags = common.build_hashtags(category, author)

    print(f"[info] Quote: \"{quote}\" — {author}")
    print(f"[info] Nature category: {category}")

    day_dir = os.path.join(common.POSTS_DIR, "picture", today)
    os.makedirs(day_dir, exist_ok=True)

    still_path = os.path.join(day_dir, "quote.jpg")
    render_quote_image(quote, author, category, still_path)
    print(f"[info] Still image rendered at {still_path}")

    track = common.fetch_openverse_track(REEL_DURATION, category)
    audio_path = None
    if track:
        audio_path = os.path.join(day_dir, "audio.mp3")
        common.prepare_audio_clip(track["local_path"], REEL_DURATION, audio_path)
        print(f"[info] Music: \"{track['name']}\" by {track['artist_name']}")

    reel_path = os.path.join(day_dir, "reel.mp4")
    render_ken_burns_reel(still_path, audio_path, reel_path)
    print(f"[info] Reel rendered at {reel_path}")

    music_credit_line = common.build_music_credit_line(track)
    caption = common.build_caption(quote, author, hashtags, music_credit_line)

    common.save_record("picture", today, {
        "date": today, "quote": quote, "author": author, "category": category,
        "hashtags": hashtags, "caption": caption,
        "music": {"name": track["name"], "artist_name": track["artist_name"]} if track else None,
    })
    common.cleanup_temp_files()
    print("[info] Wrote posts/picture/{}/record.json — commit and push this next.".format(today))


def cmd_publish():
    today = dt.date.today().isoformat()
    record = common.load_record("picture", today)
    caption = record["caption"]

    if common.DRY_RUN:
        print("[info] DRY_RUN is on — skipping Instagram publish.")
        print("----- CAPTION PREVIEW -----")
        print(caption)
        print("----------------------------")
        return

    if not (common.IG_ACCESS_TOKEN and common.IG_USER_ID):
        raise EnvironmentError("Missing IG_ACCESS_TOKEN or IG_USER_ID.")

    video_url = common.build_public_media_url("picture", today, "reel.mp4")
    print(f"[info] Using video URL: {video_url}")

    creation_id = common.create_reels_container(video_url, caption)
    print(f"[info] Media container created: {creation_id}")

    common.wait_for_container_ready(creation_id)
    media_id = common.publish_container(creation_id)
    print(f"[info] Published! Instagram media ID: {media_id}")

    common.save_record("picture", today, record, media_id=media_id)
    print("[info] Updated record.json with the Instagram media ID.")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    if command == "prepare":
        cmd_prepare()
    elif command == "publish":
        cmd_publish()
    else:
        print(f"Unknown command: {command!r}. Use 'prepare' or 'publish'.")
        sys.exit(1)
