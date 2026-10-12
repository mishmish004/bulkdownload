# bulkdownload

Paste 10, 20 or 50 Instagram reel links at once and download every video in the best available quality.

Instagram stores HD video and audio as separate streams. This tool picks the highest-resolution
video (usually 1080×1920), joins it with the audio, and saves one `.mp4` that plays on phones,
Macs and Windows.

## Quick start

Requires Python 3.8+.

```bash
python reels_dl.py
```

1. Paste your links. One per line, all on one line, or mixed in with other text all work.
2. Press **Enter** on an empty line and it starts.

Videos are saved to `~/Downloads/Instagram Reels/` as `creatorname_<id>.mp4`.

The first time, the script offers to install the download engine ([yt-dlp](https://github.com/yt-dlp/yt-dlp))
and, if you don't have it, a bundled copy of ffmpeg. You can also install them yourself:

```bash
python -m pip install -r requirements.txt
```

## Other ways to run it

```bash
python reels_dl.py links.txt                        # read links from a text file
python reels_dl.py URL1 URL2 URL3                   # pass links directly
python reels_dl.py -o ~/Videos/reels                # save somewhere else
python reels_dl.py -j 5                             # 5 downloads at a time (default 3)
python reels_dl.py --browser firefox                # use your Instagram login (see below)
python reels_dl.py --cookies cookies.txt            # use an exported cookies.txt instead
```

## Supported links

- `instagram.com/reel/...`, `/reels/...`, `/p/...` (including carousel posts) and `/tv/...`
- `instagram.com/<username>/reel/...`
- `instagram.com/share/...` share links
- Tracking parameters such as `?igsh=` are removed and duplicates are skipped automatically.

## When Instagram blocks a download

Instagram sometimes refuses downloads from people who aren't logged in. When that happens, the
tool offers to retry the blocked reels using the Instagram login saved in your browser:

- Log in to instagram.com in your browser first.
- **Firefox** works most reliably. If you use Chrome or Edge, close it before retrying.

Links that still fail are written to `failed_links.txt` in the download folder:

```bash
python reels_dl.py "~/Downloads/Instagram Reels/failed_links.txt" --browser firefox
```

If everything starts failing, Instagram probably changed something. Update the download engine:

```bash
python -m pip install -U yt-dlp
```

## Note

Only download content you have the right to save. Respect creators' copyrights and Instagram's terms.
