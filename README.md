# IGAUTO — Nature Quote Reels (two bots, one repo)

Two independent bots, each running on its own daily schedule via GitHub
Actions — your computer doesn't need to be on for either of them.

### 🌄 Picture Bot (`bot_picture.py`)
1. Fetches a quote (ZenQuotes)
2. Picks a random peaceful **nature** scene — mountains, forest, birds,
   beach, or sea — and pulls a real matching photo from Pexels
3. Renders the quote over it (serif type, soft dark scrim, your
   `@handle` watermark)
4. Animates that still photo into a slow Ken-Burns-style zoom (this is
   what turns it into a Reel instead of a static post)
5. Adds royalty-free Creative Commons background music (via Openverse)
6. Writes a real caption — not just the raw quote — and posts it as an
   Instagram **Reel**

### 🎥 Video Bot (`bot_video.py`)
1. Fetches a *different* quote (so the two bots never repeat each other
   on the same day)
2. Pulls a real, already-moving nature video clip from Pexels (same five
   categories as above)
3. Overlays the quote as centered text with a soft scrim behind it —
   same look as the picture bot, just on real footage instead of a
   Ken-Burns pan
4. Mutes the clip's original audio and replaces it with an Openverse track
5. Posts it as an Instagram Reel with the same caption style

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
| `IG_HANDLE` | *(optional)* your `@handle` for the watermark — defaults to `fragmentfiles` |

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
- **Music mood**: edit `MOOD_QUERIES` in `common.py`.
- **Your watermark handle**: set the `IG_HANDLE` secret.
- **Reel length**: `REEL_DURATION` in `bot_picture.py`, `CLIP_DURATION`
  in `bot_video.py`.
- **Ken Burns zoom speed**: the `0.15` in `zoom_expr` inside
  `render_ken_burns_reel()` in `bot_picture.py` — higher = faster zoom.
- **Posting times**: the `cron` schedules (step 5 above).
