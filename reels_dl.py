#!/usr/bin/env python3
"""
Instagram Reels bulk downloader.

Paste any number of reel / post links (one per line, space- or comma-separated,
or even jammed together) and every video is saved in the best available quality.

  python reels_dl.py                    paste links, then press Enter on an empty line
  python reels_dl.py links.txt          read links from a text file
  python reels_dl.py URL [URL ...]      pass links directly

Options:
  -o, --out DIR        where to save   (default: ~/Downloads/Instagram Reels)
  -b, --browser NAME   borrow your Instagram login from this browser
                       (firefox, chrome, edge, brave, safari, opera, vivaldi, chromium)
  -j, --jobs N         downloads at the same time (default: 3)

Needs Python 3.8+. yt-dlp (and a bundled ffmpeg, if you don't have one) are
installed automatically on first run after you confirm.
"""

import argparse
import importlib
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DEFAULT_OUT = Path.home() / "Downloads" / "Instagram Reels"
BROWSERS = ("firefox", "chrome", "edge", "brave", "safari", "opera", "vivaldi", "chromium")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Anything that looks like an instagram.com link.
URL_RE = re.compile(r"(?:https?://)?(?:www\.|m\.)?instagram\.com/[^\s,;\"'<>()\[\]]+", re.I)
# The reel/post part of a link: /reel/ID, /reels/ID, /p/ID, /tv/ID, /username/reel/ID ...
POST_RE = re.compile(r"/(reels?|p|tv)/([\w-]+)", re.I)
LOGIN_HINTS = ("login required", "rate-limit", "rate limit", "not available",
               "empty media response", "401", "403", "checkpoint", "cookies")

print_lock = threading.Lock()


def say(*args, **kwargs):
    with print_lock:
        print(*args, **kwargs, flush=True)


def ask(prompt):
    if not sys.stdin.isatty():
        return ""
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


# ---------------------------------------------------------------- links

def resolve_share_link(url):
    """instagram.com/share/... links redirect to the real reel URL."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.geturl()
    except Exception:
        return url


def extract_links(text, resolve=True):
    """Pull every reel/post link out of messy pasted text, normalized and de-duplicated."""
    # Split links that were pasted back-to-back with no separator.
    text = re.sub(r"(?<=\S)(https?://)", r" \1", text)
    links, skipped = [], []
    for raw in URL_RE.findall(text):
        url = raw if raw.lower().startswith("http") else "https://" + raw
        if "/share/" in url.lower():
            if not resolve:
                links.append(url)
                continue
            final = resolve_share_link(url)
            if "/share/" in final.lower():
                links.append(url)  # couldn't resolve; let yt-dlp try it as-is
                continue
            url = final
        m = POST_RE.search(urllib.parse.unquote(url))
        if not m or m.group(2).lower() == "audio":
            skipped.append(url)
            continue
        kind = "reel" if m.group(1).lower().startswith("reel") else m.group(1).lower()
        links.append(f"https://www.instagram.com/{kind}/{m.group(2)}/")
    return list(dict.fromkeys(links)), skipped


def read_pasted_links():
    print("Paste your Instagram links, then press Enter on an empty line:\n")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            if URL_RE.search("\n".join(lines)):
                break
            continue
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------- dependencies

def pip_install(package):
    say(f"Installing {package} ...")
    result = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "--quiet", package])
    importlib.invalidate_caches()
    return result.returncode == 0


def load_yt_dlp():
    try:
        import yt_dlp
        return yt_dlp
    except ImportError:
        pass
    answer = ask("yt-dlp (the download engine) isn't installed. Install it now? [Y/n] ")
    if answer.lower() in ("", "y", "yes") and sys.stdin.isatty() and pip_install("yt-dlp"):
        try:
            import yt_dlp
            return yt_dlp
        except ImportError:
            say("Installed - please run the script again.")
            sys.exit(0)
    say("\nyt-dlp is required. Install it with:\n"
        f"    {Path(sys.executable).name} -m pip install -U yt-dlp")
    sys.exit(1)


def find_ffmpeg():
    """ffmpeg lets us merge Instagram's separate HD video + audio streams."""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    answer = ask("ffmpeg isn't installed; without it some reels come out in lower quality.\n"
                 "Install a bundled copy now (~30 MB)? [Y/n] ")
    if answer.lower() in ("", "y", "yes") and sys.stdin.isatty() and pip_install("imageio-ffmpeg"):
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    say("Continuing without ffmpeg (single-file quality).\n")
    return None


# ---------------------------------------------------------------- downloading

class _SilentLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def build_options(out_dir, ffmpeg, browser=None, cookie_file=None):
    opts = {
        "outtmpl": str(out_dir / "%(channel,uploader_id|instagram)s_%(id)s.%(ext)s"),
        # Best video + best audio merged; falls back to the best single file.
        "format": "bv*+ba/b" if ffmpeg else "b",
        # Highest resolution first; at equal resolution prefer H.264/AAC so it plays everywhere.
        "format_sort": ["res", "vcodec:h264", "acodec:aac"],
        "merge_output_format": "mp4",
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _SilentLogger(),
    }
    if ffmpeg and ffmpeg != "ffmpeg":
        opts["ffmpeg_location"] = ffmpeg
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    if cookie_file:
        opts["cookiefile"] = cookie_file
    return opts


def login_error(yt_dlp, opts):
    """Load browser/file cookies once up front so a bad choice fails fast, not once per reel."""
    if not (opts.get("cookiesfrombrowser") or opts.get("cookiefile")):
        return None
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.cookiejar
    except Exception as err:
        return clean_error(err)
    return None


def saved_files(info):
    if not info:
        return
    for entry in info.get("entries") or []:
        yield from saved_files(entry)
    for dl in info.get("requested_downloads") or []:
        if dl.get("filepath"):
            yield dl["filepath"]


def clean_error(err):
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(err))
    msg = re.sub(r"^ERROR:\s*(\[\w+\]\s*)?([\w-]+:\s*)?", "", msg)
    for noise in (" Use --cookies", "; please report this issue", " (caused by "):
        msg = msg.split(noise)[0]
    return msg.strip()


def download_all(yt_dlp, links, opts, jobs):
    """Download every link; returns list of (url, error) for the ones that failed."""
    total, done, failed = len(links), 0, []
    width = len(str(total))

    def work(url):
        with yt_dlp.YoutubeDL(opts) as ydl:
            return list(saved_files(ydl.extract_info(url, download=True)))

    pool = ThreadPoolExecutor(max_workers=max(1, jobs))
    futures = {pool.submit(work, url): url for url in links}
    try:
        for fut in as_completed(futures):
            url = futures[fut]
            done += 1
            tag = f"[{done:>{width}}/{total}]"
            try:
                files = fut.result()
            except Exception as err:
                failed.append((url, clean_error(err)))
                say(f"{tag} FAILED  {url}\n{' ' * len(tag)}         {failed[-1][1]}")
                continue
            if not files:
                say(f"{tag} skipped {url} (no video found)")
            for path in files:
                size = os.path.getsize(path) / 1_048_576 if os.path.exists(path) else 0
                say(f"{tag} ok      {Path(path).name}  ({size:.1f} MB)")
    except KeyboardInterrupt:
        for fut in futures:
            fut.cancel()
        raise
    finally:
        pool.shutdown(wait=True)
    return failed


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(
        description="Download Instagram reels in bulk, in the best available quality.")
    parser.add_argument("inputs", nargs="*",
                        help="reel links, or a .txt file containing links (omit to paste)")
    parser.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT,
                        help=f"output folder (default: {DEFAULT_OUT})")
    parser.add_argument("-b", "--browser", choices=BROWSERS,
                        help="use your Instagram login from this browser")
    parser.add_argument("--cookies", metavar="FILE", help="cookies.txt file (Netscape format)")
    parser.add_argument("-j", "--jobs", type=int, default=3,
                        help="parallel downloads (default: 3)")
    args = parser.parse_args()

    interactive = not args.inputs and sys.stdin.isatty()
    if args.inputs:
        chunks = []
        for item in args.inputs:
            p = Path(item)
            chunks.append(p.read_text(encoding="utf-8", errors="ignore") if p.is_file() else item)
        text = "\n".join(chunks)
    elif sys.stdin.isatty():
        text = read_pasted_links()
    else:
        text = sys.stdin.read()

    links, skipped = extract_links(text)
    for url in skipped:
        say(f"Ignoring (not a reel/post link): {url}")
    if not links:
        say("No Instagram reel/post links found.")
        return 1

    yt_dlp = load_yt_dlp()
    ffmpeg = find_ffmpeg()
    args.out.mkdir(parents=True, exist_ok=True)

    quality = "best quality" if ffmpeg else "single-file quality"
    say(f"\nFound {len(links)} link(s). Saving to {args.out}  ({quality}, {args.jobs} at a time)\n")
    opts = build_options(args.out, ffmpeg, args.browser, args.cookies)
    err = login_error(yt_dlp, opts)
    if err:
        say(f"Couldn't load your Instagram login: {err}")
        return 1
    failed = download_all(yt_dlp, links, opts, args.jobs)

    # Instagram often blocks anonymous downloads; offer one retry with a browser login.
    login_failures = [u for u, e in failed if any(h in e.lower() for h in LOGIN_HINTS)]
    if login_failures and not (args.browser or args.cookies) and interactive:
        say(f"\n{len(login_failures)} reel(s) were blocked - Instagram wants a login for those.")
        say("Make sure you're logged in to instagram.com in a browser (Firefox works most reliably;")
        say("close Chrome/Edge first if you use those).")
        browser = ask(f"Browser to borrow the login from ({', '.join(BROWSERS)}), "
                      "or Enter to skip: ").lower()
        if browser in BROWSERS:
            say("")
            retry_opts = build_options(args.out, ffmpeg, browser)
            err = login_error(yt_dlp, retry_opts)
            if err:
                say(f"Couldn't load your {browser} login: {err}")
            else:
                still_failed = download_all(yt_dlp, login_failures, retry_opts, args.jobs)
                failed = [f for f in failed if f[0] not in login_failures] + still_failed

    ok = len(links) - len(failed)
    say(f"\nDone: {ok} downloaded, {len(failed)} failed.  Files are in: {args.out}")
    if failed:
        failed_file = args.out / "failed_links.txt"
        failed_file.write_text("\n".join(u for u, _ in failed) + "\n", encoding="utf-8")
        say(f"Failed links saved to {failed_file}")
        say("Retry them with:  python reels_dl.py "
            f"\"{failed_file}\" --browser firefox")
        say("If everything fails, update the engine:  "
            f"{Path(sys.executable).name} -m pip install -U yt-dlp")
    return 1 if failed else 0


if __name__ == "__main__":
    launched_bare = len(sys.argv) == 1 and sys.stdin.isatty()
    try:
        code = main()
    except KeyboardInterrupt:
        say("\nStopped.")
        code = 130
    if launched_bare:  # keep a double-clicked window open so the summary can be read
        ask("\nPress Enter to close...")
    sys.exit(code)
