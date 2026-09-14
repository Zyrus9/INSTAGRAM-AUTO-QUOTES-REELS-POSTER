"""
Video Bot — Nature Clip Quote Reel
-----------------------------------
Fetches a (different) daily quote, grabs a real calm nature video clip
(mountains, forest, birds, beach, or sea) from Pexels, overlays the quote
as centered text with a soft scrim behind it, mutes the clip's original
audio and replaces it with Creative-Commons background music — then
posts it as an Instagram Reel via the Graph API.

Same two-phase pattern as bot_picture.py: prepare -> commit/push -> publish.

Usage:
    python bot_video.py prepare
    python bot_video.py publish
"""

import os
import sys
import subprocess
import datetime as dt

from PIL import ImageFont, ImageDraw, Image

import common

CLIP_DURATION = 10  # seconds — trimmed length of the final reel


# --------------------------------------------------------------------------
# Text wrapping (measured with PIL so it matches what ffmpeg will draw,
# since ffmpeg's drawtext has no word-wrap of its own)
# --------------------------------------------------------------------------

def wrap_quote_lines(quote, font_path, font_size, max_width_px):
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    dummy = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    words = quote.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if dummy.textlength(trial, font=font) <= max_width_px:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def escape_for_drawtext(text):
    """ffmpeg drawtext treats : and \\ and ' specially when passed as a
    literal filter argument; we sidestep nearly all of that by writing the
    text to a file and using textfile=, but the file content itself still
    needs literal backslashes doubled for drawtext's own parser."""
    return text.replace("\\", "\\\\").replace("%", "\\%")


# --------------------------------------------------------------------------
# Video processing
# --------------------------------------------------------------------------

def get_video_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def render_quote_reel(source_video_path, quote, author, audio_path, out_path,
                       duration=CLIP_DURATION):
    w, h = common.REEL_SIZE
    font_path = common.get_font_path("regular") or "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
    italic_path = common.get_font_path("italic") or font_path

    margin = 100
    max_width_px = w - 2 * margin
    font_size = 56
    lines = wrap_quote_lines(quote, font_path, font_size, max_width_px)
    while len(lines) > 7 and font_size > 32:
        font_size -= 4
        lines = wrap_quote_lines(quote, font_path, font_size, max_width_px)

    author_line = f"\u2014 {author}"
    quote_text = "\n".join(lines)

    quote_txt_path = out_path + ".quote.txt"
    author_txt_path = out_path + ".author.txt"
    with open(quote_txt_path, "w") as f:
        f.write(escape_for_drawtext(quote_text))
    with open(author_txt_path, "w") as f:
        f.write(escape_for_drawtext(author_line))

    line_height = int(font_size * 1.45)
    block_height = line_height * len(lines) + 70

    src_duration = get_video_duration(source_video_path)
    # Pick a start offset so we're not always using the exact first frame
    # (helps avoid intro logos/fades some stock clips have).
    start_offset = min(1.5, max(src_duration - duration, 0))

    # No drawbox behind the text anymore — that hard-edged rectangle was
    # the "black patch" showing up on every reel. Legibility now comes
    # from a slightly stronger frame-wide dim (eq=brightness) plus a
    # black outline + shadow directly on the letters (like subtitle
    # text), so there's no separate dark box sitting on the footage.
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        f"eq=brightness=-0.08,"
        f"drawtext=textfile={quote_txt_path}:fontfile={font_path}:fontsize={font_size}:"
        f"fontcolor=white:line_spacing=14:x=(w-text_w)/2:y=(h-text_h)/2-40:"
        f"bordercolor=black@0.75:borderw=3:"
        f"shadowcolor=black@0.7:shadowx=2:shadowy=2,"
        f"drawtext=textfile={author_txt_path}:fontfile={italic_path}:fontsize=34:"
        f"fontcolor=0xEBEBEB:x=(w-text_w)/2:y=(h/2)+{block_height // 2 - 70}:"
        f"bordercolor=black@0.75:borderw=2:"
        f"shadowcolor=black@0.7:shadowx=1:shadowy=1,"
        f"{common.build_watermark_drawtext_filter()}"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_offset), "-i", source_video_path,
    ]
    if audio_path:
        cmd += ["-i", audio_path]
    cmd += ["-t", str(duration), "-vf", vf, "-map", "0:v"]
    if audio_path:
        cmd += ["-map", "1:a", "-c:a", "aac", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += [
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    os.remove(quote_txt_path)
    os.remove(author_txt_path)
    return out_path


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def cmd_prepare():
    today = dt.date.today().isoformat()
    print(f"[info] Preparing video-bot reel for {today} (DRY_RUN={common.DRY_RUN})")

    quote, author = common.fetch_quote_alt()
    common.mark_quote_used(quote)
    category = common.pick_nature_category()
    hashtags = common.build_hashtags(category, author)

    print(f"[info] Quote: \"{quote}\" — {author}")
    print(f"[info] Nature category: {category}")

    day_dir = os.path.join(common.POSTS_DIR, "video", today)
    os.makedirs(day_dir, exist_ok=True)

    source_clip = common.fetch_nature_video(category, min_duration=CLIP_DURATION)
    if not source_clip:
        raise RuntimeError(
            "Could not fetch a nature video clip from Pexels (check PEXELS_API_KEY "
            "and network). The video bot has no gradient fallback since it needs "
            "real footage."
        )

    track = common.fetch_openverse_track(CLIP_DURATION, category, alt=True)
    audio_path = None
    if track:
        audio_path = os.path.join(day_dir, "audio.mp3")
        common.prepare_audio_clip(track["local_path"], CLIP_DURATION, audio_path)
        print(f"[info] Music: \"{track['name']}\" by {track['artist_name']}")

    reel_path = os.path.join(day_dir, "reel.mp4")
    render_quote_reel(source_clip, quote, author, audio_path, reel_path, duration=CLIP_DURATION)
    print(f"[info] Reel rendered at {reel_path}")

    music_credit_line = common.build_music_credit_line(track)
    caption = common.build_caption(quote, author, hashtags, music_credit_line)

    common.save_record("video", today, {
        "date": today, "quote": quote, "author": author, "category": category,
        "hashtags": hashtags, "caption": caption,
        "music": {"name": track["name"], "artist_name": track["artist_name"]} if track else None,
    })
    common.cleanup_temp_files()
    print("[info] Wrote posts/video/{}/record.json — commit and push this next.".format(today))


def cmd_publish():
    today = dt.date.today().isoformat()
    record = common.load_record("video", today)
    caption = record["caption"]

    if common.DRY_RUN:
        print("[info] DRY_RUN is on — skipping Instagram publish.")
        print("----- CAPTION PREVIEW -----")
        print(caption)
        print("----------------------------")
        return

    if not (common.IG_ACCESS_TOKEN and common.IG_USER_ID):
        raise EnvironmentError("Missing IG_ACCESS_TOKEN or IG_USER_ID.")

    video_url = common.build_public_media_url("video", today, "reel.mp4")
    print(f"[info] Using video URL: {video_url}")

    creation_id = common.create_reels_container(video_url, caption)
    print(f"[info] Media container created: {creation_id}")

    common.wait_for_container_ready(creation_id)
    media_id = common.publish_container(creation_id)
    print(f"[info] Published! Instagram media ID: {media_id}")

    common.save_record("video", today, record, media_id=media_id)
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
