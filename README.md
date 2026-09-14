# IGAUTO — Nature Quote Reels (two bots, one repo)

Two independent bots, each running on its own daily schedule via GitHub
Actions — your computer doesn't need to be on for either of them.

### 🌄 Picture Bot (`bot_picture.py`)
1. Fetches a quote (ZenQuotes)
2. Picks a random peaceful **nature** scene — mountains, forest, birds,
   beach, or sea — and pulls a real matching photo from Pexels
3. Renders the quote over it (serif type, drop-shadowed text — no
   background box)
4. Animates that still photo into a slow Ken-Burns-style zoom (this is
   what turns it into a Reel instead of a static post)
5. Adds royalty-free Creative Commons background music (via Openverse),
   picked to match the scene's mood (ocean-ish for beach/sea, birdsong-ish
   for birds, etc.)
6. Stamps the `fragmentfiles` watermark at a fixed spot at the bottom
7. Writes a real caption — not just the raw quote — and posts it as an
   Instagram **Reel**

### 🎥 Video Bot (`bot_video.py`)
1. Fetches a *different* quote (so the two bots never repeat each other
   on the same day)
2. Pulls a real, already-moving nature video clip from Pexels (same five
   categories as above)
3. Overlays the quote as centered text with a black outline + drop
   shadow for legibility (no background box)
4. Mutes the clip's original audio and replaces it with an Openverse
   track picked to match the scene's mood
5. Stamps the `fragmentfiles` watermark at a fixed spot at the bottom
6. Posts it as an Instagram Reel with the same caption style

## Recent changes

- **Background music, hardened + deduped**: both bots already added
  Openverse music to every reel, but if Openverse came up empty on the
  first few mood queries it used to just give up and post silently.
  Now every mood query in the pool is tried before giving up, so a
  silent reel should be rare going forward. Music tracks are also
  tracked in `posts/used_history.json` (same idea as quotes and
  photos) so the same track won't repeat for a couple of months.
- **Watermark**: both bots now stamp `fragmentfiles` at a fixed spot at
  the bottom of every reel (baked into the video itself, after any
  zoom/crop, so it never drifts or gets cropped). Change the text by
  setting the `IG_HANDLE` secret to something else.
- **Pause switches**: two separate repository *variables* —
  `QUOTE_POSTING_ENABLED` and `VIDEO_POSTING_ENABLED` — each gate their
  own bot's daily scheduled runs independently. See "Pausing/resuming
  posting" below.
- **Black patch removed**: the video bot used to draw a solid dark box
  behind the quote text for readability — that's gone. Both bots now
  rely on a drop shadow / black outline directly on the letters instead,
  so there's no rectangle sitting on top of the footage.
- **Better-matching music**: background tracks are now searched per
  nature category (e.g. ocean-ish moods for beach/sea clips, birdsong-ish
  for birds) instead of one generic "calm ambient" pool for everything.
  It still depends on what Openverse actually has available that day, so
  it won't always be a perfect nature-sound match, but it'll lean toward
  the right vibe far more often than before.

## Pausing/resuming posting (the ON/OFF switches)

Each bot has its own independent switch, so you can pause one without
touching the other.

**Settings → Secrets and variables → Actions → Variables tab → New
repository variable.**

| Variable name | Controls | Value | Effect |
|---|---|---|---|
| `QUOTE_POSTING_ENABLED` | Picture/text-quote bot (`daily-quote-post.yml`) | `false` | Pauses this bot's daily scheduled posts |
| `QUOTE_POSTING_ENABLED` | " | `true` (or delete the variable) | Resumes it |
| `VIDEO_POSTING_ENABLED` | Video bot (`daily-video-post.yml`) | `false` | Pauses this bot's daily scheduled posts |
| `VIDEO_POSTING_ENABLED` | " | `true` (or delete the variable) | Resumes it |

When a bot's variable is set to `false`, its scheduled (cron) run shows
as **skipped** in the Actions tab instead of running — nothing gets
generated or posted for that bot. The other bot keeps running normally
unless you've also set its own variable. Manually running a workflow via
**Actions → [workflow name] → Run workflow** still works regardless of
either switch, so you can always test or force a one-off post while
paused.


Both keep a record (quote + category + music + caption) under
`posts/picture/YYYY-MM-DD/` and `posts/video/YYYY-MM-DD/`.

## How the hosting trick works (unchanged from before)

Instagram's API needs a public URL for the media file. Instead of a
third-party host, each workflow commits the rendered `.mp4` straight
into this repo and uses its `raw.githubusercontent.com` link. That's why
each workflow runs in three steps: **prepare → commit/push → publish**
— the file has to already be public before Instagram can fetch it.

**This means the repo needs to be public.** Nothing sensitive lives in
the code or the `posts/` folder — your tokens stay in GitHub Secrets
(encrypted regardless of repo visibility). The only public things are
the bots' code and the same reels that are about to be posted anyway.

> **Heads up:** this hosting trick is proven for images; video is a
> little more demanding (bigger files, and `raw.githubusercontent.com`
> doesn't always send a perfect `Content-Type: video/mp4` header). If
> Instagram ever fails to fetch a video container (check the "Publish to
> Instagram" step's logs for the error), the fix is to host the `.mp4`
> as a GitHub **Release asset** instead of a raw file — that's a small
> change, just ask and it can be added.

## 1. Make the repo public

**Settings → General → Danger Zone → Change visibility → Public.**

## 2. Get your API key (just one — Pexels)

| Service | What it's for | Get it at |
|---|---|---|
| Pexels | Nature photos + videos | https://www.pexels.com/api/ — sign up, key shown immediately |

Background music comes from **Openverse** (a Creative Commons search
engine run by the WordPress Foundation) — **no signup and no API key
needed** for this one, it's a fully open public API. The bots only pull
tracks licensed **CC0 / Public Domain / plain CC-BY** (nothing with a
non-commercial or share-alike restriction, since this is a commercial
IG account), and automatically add a credit line to the caption when
one's legally required, e.g.
`🎵 "Moment of Peace" — MickeysCat (CC BY, via Openverse)`, or a plain
"Public Domain" credit when none is required. No manual attribution
work needed either way.

> Note on Jamendo, in case you tried it before: Jamendo's own API terms
> restrict free usage to *non-commercial* projects — anything monetized
> (ads, affiliate links, brand deals) technically needs a paid license
> from them. Openverse sidesteps that entirely since we only pull
> tracks explicitly cleared for commercial use.

## 3. Add your secrets

**Settings → Secrets and variables → Actions → New repository secret.**

| Secret name | Value |
|---|---|
| `IG_ACCESS_TOKEN` | Your long-lived Instagram access token |
| `IG_USER_ID` | Your Instagram business account ID |
| `PEXELS_API_KEY` | From step 2 |
| `IG_HANDLE` | *(optional)* watermark text stamped on every reel — defaults to `fragmentfiles` |

(`GITHUB_REPOSITORY` / `GITHUB_REF_NAME` are provided automatically by
Actions.)

If `PEXELS_API_KEY` is missing, the **picture bot** falls back to a
plain gradient background — but the **video bot** has no fallback (it
needs real footage), so it will fail without a Pexels key. If Openverse
has no safe track available on a given day (rare, but it's a public API
with no uptime guarantee), both bots just post a silent reel instead of
failing.

## 4. Test before trusting it

**On GitHub, without posting anything:**
Actions tab → pick either workflow ("Daily Quote Post (Picture Bot)" or
"...(Video Bot)") → **Run workflow** → check "Dry run" → **Run workflow**.
The reel still gets committed to `posts/`, so you can open the `.mp4`
right in the repo to see/hear it, and the "Publish to Instagram" step's
logs show the caption preview.

**Locally:**
```bash
pip install -r requirements.txt
sudo apt-get install -y ffmpeg   # if you don't already have it

DRY_RUN=true PEXELS_API_KEY=... python bot_picture.py prepare
DRY_RUN=true python bot_picture.py publish   # just prints the caption

DRY_RUN=true PEXELS_API_KEY=... python bot_video.py prepare
DRY_RUN=true python bot_video.py publish
```
This writes `posts/<bot>/<today>/reel.mp4` so you can preview it — no
network calls to Instagram happen in dry-run mode.

**A real live test post:** run either workflow again with "Dry run"
unchecked, or just wait for its schedule.

## 5. Adjust posting times

Edit the `cron` line in each workflow file under `.github/workflows/`.
Currently:
- Picture bot: `0 13 * * *` (13:00 UTC = 6:30 PM IST)
- Video bot: `0 15 * * *` (15:00 UTC = 8:30 PM IST)

Cron times are always in UTC.

## Heads up: token expiry

Long-lived Instagram tokens last about **60 days**. Set yourself a
reminder to regenerate one every ~50 days from the "API setup with
Instagram login" page in your Meta app dashboard, and update the
`IG_ACCESS_TOKEN` secret.

## Customizing

- **Nature categories / search terms / hashtags**: edit
  `NATURE_CATEGORIES` near the top of `common.py` — this drives both
  bots' photo and video search.
- **Caption wording / hooks**: edit `CAPTION_HOOKS` and `build_caption()`
  in `common.py`.
- **Music mood**: edit `MOOD_QUERIES` (generic pool) or
  `CATEGORY_MOOD_QUERIES` (per nature-category matching) in `common.py`.
- **Your watermark text**: set the `IG_HANDLE` secret, or edit
  `build_watermark_drawtext_filter()` in `common.py` for size/position.
- **Reel length**: `REEL_DURATION` in `bot_picture.py`, `CLIP_DURATION`
  in `bot_video.py`.
- **Ken Burns zoom speed**: the `0.15` in `zoom_expr` inside
  `render_ken_burns_reel()` in `bot_picture.py` — higher = faster zoom.
- **Posting times**: the `cron` schedules (step 5 above).
