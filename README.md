<div align="center">

# jackthesolo

![Python](https://img.shields.io/badge/python-%3E%3D3.9-blue)
![Platform](https://img.shields.io/badge/platform-linux_%7C_windows_%7C_macos-lightgrey)
[![PyPI](https://img.shields.io/pypi/v/jackthesolo)](https://pypi.org/project/jackthesolo)

**One command to download almost anything. Paste a URL, done.**

</div>

## Install

```bash
pip install jackthesolo
sudo systemctl enable --now tor   # one time only
```

## Use

```bash
jackthesolo "URL"
```

Files land in `~/Downloads`. The URL type is auto-detected.

```bash
jackthesolo "https://www.tiktok.com/@u/video/123" --cookies cookies.txt
jackthesolo "https://www.youtube.com/watch?v=..." --cookies yt_cookies.txt
jackthesolo "https://www.scribd.com/document/123/Title"
jackthesolo "https://…/shared?..." --cookies cookies.txt --output-file Document.pdf
jackthesolo "URL" -a
jackthesolo "URL" -q 720
jackthesolo "URL" --info
jackthesolo "https://www.tiktok.com/@u" --cookies cookies.txt --max 5
jackthesolo --check
```

Need cookies? Open the site logged in, export with the
"Get cookies.txt LOCALLY" extension, then pass `--cookies cookies.txt`.
Never share your cookie files.

Stuck? Run `jackthesolo --check`, or read `man jackthesolo`.

## Other shells and devices

Same commands work in PowerShell (`pwsh`), with two notes: use `man`
only on Linux (on Windows read `--help` instead), and install Tor via
Tor Browser or the Expert Bundle, then point at it with
`--proxy socks5h://127.0.0.1:9150`.

On Android (Termux), install the basics first:

```bash
pkg install python ffmpeg
pip install jackthesolo
```

What works there: direct files and media downloads (yt-dlp). What likely
does not: browser modes (cloud, scribd) need desktop Chromium, and the
TikTok engine needs `curl-cffi` which has no Android build. For anonymity
on Android, run Orbot first so port 9050 is open, otherwise downloads
are refused per the fail-closed rule. Termux is untested, reports welcome.

## Credits

* Scribd engine adapted from
  [themrsami/scribd-downloader](https://github.com/themrsami/scribd-downloader)
  (MIT licensed).
* Media mode uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense).

MIT licensed (see `LICENSE`).
