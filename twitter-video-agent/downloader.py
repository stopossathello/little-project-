"""X (Twitter) 推文影片下載核心，包裝 yt-dlp。

可以單獨當命令列工具使用，不需要 Anthropic API key：

    python downloader.py https://x.com/SpaceX/status/1732824684683784516 --max-height 720
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from yt_dlp.utils import DownloadError

TWEET_HOSTS = {
    "x.com",
    "www.x.com",
    "mobile.x.com",
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
    "m.twitter.com",
    # 常見的轉嵌入服務，網址結構跟原站一樣
    "fxtwitter.com",
    "vxtwitter.com",
    "fixupx.com",
    "fixvx.com",
}

_STATUS_PATH = re.compile(
    r"^/(?:i/web|i|(?P<user>[A-Za-z0-9_]{1,15}))/status/(?P<id>\d+)"
    r"(?:/(?:video|photo)/(?P<index>\d+))?/?$"
)

# 檔名：帳號_推文ID_媒體ID.副檔名，同一則推文裡的多支影片不會互相覆蓋
OUTPUT_TEMPLATE = "%(uploader_id|unknown)s_%(display_id,id)s_%(id)s.%(ext)s"
# 只抓聲音時用不同檔名。轉檔後 yt-dlp 會刪掉中間檔，共用檔名會把之前下載的影片刪掉
AUDIO_OUTPUT_TEMPLATE = "%(uploader_id|unknown)s_%(display_id,id)s_%(id)s_audio.%(ext)s"


class TweetVideoError(Exception):
    """網址不合法、推文沒有影片或下載失敗。"""


class _SilentLogger:
    """錯誤一律由 TweetVideoError 回報，不讓 yt-dlp 自己印到終端機。"""

    def debug(self, msg: str) -> None:
        pass

    info = warning = error = debug


@dataclass(frozen=True)
class TweetRef:
    url: str
    tweet_id: str
    index: int | None = None


@dataclass
class DownloadOptions:
    out_dir: Path = Path("downloads")
    cookies_file: str | None = None
    cookies_from_browser: str | None = None


def parse_tweet_url(raw: str) -> TweetRef:
    """把各種推文網址整理成 https://x.com/<帳號>/status/<ID>。"""
    text = raw.strip()
    if not re.match(r"^https?://", text, re.IGNORECASE):
        text = "https://" + text
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if host not in TWEET_HOSTS:
        raise TweetVideoError(f"不是 X / Twitter 的網址：{raw}")
    match = _STATUS_PATH.match(parsed.path)
    if not match:
        raise TweetVideoError(f"找不到推文 ID，網址要長得像 https://x.com/<帳號>/status/<數字>：{raw}")
    user = match["user"] or "i"
    index = int(match["index"]) if match["index"] else None
    return TweetRef(
        url=f"https://x.com/{user}/status/{match['id']}",
        tweet_id=match["id"],
        index=index,
    )


def _base_params(opts: DownloadOptions) -> dict:
    params = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _SilentLogger(),
        # 只允許 Twitter 系列的 extractor，避免推文裡的外部連結被拿去下載
        "allowed_extractors": ["twitter.*"],
        "restrictfilenames": True,
    }
    if opts.cookies_file:
        params["cookiefile"] = opts.cookies_file
    if opts.cookies_from_browser:
        params["cookiesfrombrowser"] = (opts.cookies_from_browser,)
    return params


def _entries(info: dict) -> list[dict]:
    if info.get("_type") == "playlist":
        return [e for e in info.get("entries") or [] if e]
    return [info]


def _pick(entries: list[dict], index: int | None) -> list[tuple[int, dict]]:
    """回傳 (第幾支, 影片資料)，編號從 1 開始。"""
    numbered = list(enumerate(entries, 1))
    if index is None:
        return numbered
    if not 1 <= index <= len(entries):
        raise TweetVideoError(f"這則推文只有 {len(entries)} 支影片，沒有第 {index} 支")
    return [numbered[index - 1]]


def _extract(ydl: yt_dlp.YoutubeDL, ref: TweetRef) -> dict:
    try:
        info = ydl.extract_info(ref.url, download=False)
    except DownloadError as exc:
        raise TweetVideoError(_clean_error(exc)) from exc
    if not info:
        raise TweetVideoError("yt-dlp 沒有回傳任何資料")
    return info


def _clean_error(exc: DownloadError) -> str:
    message = str(exc).removeprefix("ERROR: ").strip()
    if "No video could be found" in message:
        return "這則推文裡沒有影片"
    if any(key in message for key in ("NSFW", "age-restricted", "login", "log in", "authentication")):
        return message + "（這則推文需要登入才看得到，請用 --cookies 或 --cookies-from-browser 提供登入狀態）"
    return message


def inspect_tweet(url: str, opts: DownloadOptions) -> dict:
    """查推文裡有哪些影片，不下載。"""
    ref = parse_tweet_url(url)
    with yt_dlp.YoutubeDL(_base_params(opts) | {"skip_download": True}) as ydl:
        info = _extract(ydl, ref)
    entries = _entries(info)
    first = entries[0] if entries else info
    videos = []
    for number, entry in enumerate(entries, 1):
        heights = sorted({f["height"] for f in entry.get("formats") or [] if f.get("height")})
        videos.append({
            "index": number,
            "duration_sec": round(entry["duration"], 1) if entry.get("duration") else None,
            "available_heights": heights,
        })
    return {
        "url": ref.url,
        "tweet_id": ref.tweet_id,
        "uploader": first.get("uploader"),
        "uploader_id": first.get("uploader_id"),
        "text": first.get("description"),
        "requested_index": ref.index,
        "videos": videos,
    }


def download_tweet(
    url: str,
    opts: DownloadOptions,
    max_height: int | None = None,
    video_index: int | None = None,
    audio_only: bool = False,
) -> list[dict]:
    """下載推文裡的影片，回傳每個檔案的路徑、畫質和大小。"""
    ref = parse_tweet_url(url)
    index = video_index if video_index is not None else ref.index
    opts.out_dir.mkdir(parents=True, exist_ok=True)

    template = AUDIO_OUTPUT_TEMPLATE if audio_only else OUTPUT_TEMPLATE
    params = _base_params(opts) | {"outtmpl": str(opts.out_dir / template)}
    if audio_only:
        params["format"] = "bestaudio/best"
        params["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]
    else:
        params["format"] = "bv*+ba/b"
        params["merge_output_format"] = "mp4"
        if max_height:
            # 選不超過 max_height 的最高畫質；全部都超過時選最接近的
            params["format_sort"] = [f"res:{max_height}"]

    results = []
    with yt_dlp.YoutubeDL(params) as ydl:
        info = _extract(ydl, ref)
        for number, entry in _pick(_entries(info), index):
            try:
                done = ydl.process_ie_result(entry, download=True)
            except DownloadError as exc:
                raise TweetVideoError(_clean_error(exc)) from exc
            for item in done.get("requested_downloads") or [done]:
                path = Path(item.get("filepath") or done.get("filepath") or "")
                if not path.is_file():
                    continue
                results.append({
                    "file": str(path.resolve()),
                    "index": number,
                    "uploader_id": done.get("uploader_id"),
                    "width": None if audio_only else done.get("width"),
                    "height": None if audio_only else done.get("height"),
                    "duration_sec": round(done["duration"], 1) if done.get("duration") else None,
                    "size_mb": round(path.stat().st_size / 1_048_576, 2),
                })
    if not results:
        raise TweetVideoError("下載結束但找不到輸出檔案")
    return results


def list_downloads(opts: DownloadOptions) -> list[dict]:
    if not opts.out_dir.is_dir():
        return []
    files = sorted(
        (p for p in opts.out_dir.iterdir() if p.is_file() and not p.name.endswith((".part", ".ytdl"))),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [{"file": str(p.resolve()), "size_mb": round(p.stat().st_size / 1_048_576, 2)} for p in files]


def add_cookie_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", default="downloads", help="輸出資料夾（預設 ./downloads）")
    parser.add_argument("--cookies", help="Netscape 格式的 cookies.txt，用來下載需要登入的推文")
    parser.add_argument("--cookies-from-browser", help="直接讀瀏覽器的登入狀態，例如 chrome、firefox、safari")


def options_from_args(args: argparse.Namespace) -> DownloadOptions:
    return DownloadOptions(
        out_dir=Path(args.out).expanduser(),
        cookies_file=args.cookies,
        cookies_from_browser=args.cookies_from_browser,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="下載 X (Twitter) 推文裡的影片")
    parser.add_argument("urls", nargs="+", help="推文網址，可以一次給多個")
    parser.add_argument("--max-height", type=int, help="畫質上限，例如 720")
    parser.add_argument("--index", type=int, help="推文有多支影片時只抓第幾支（從 1 開始）")
    parser.add_argument("--audio-only", action="store_true", help="只抓聲音（m4a）")
    parser.add_argument("--info", action="store_true", help="只列出影片資訊，不下載")
    add_cookie_args(parser)
    args = parser.parse_args(argv)
    opts = options_from_args(args)

    failed = 0
    for url in args.urls:
        try:
            if args.info:
                print(json.dumps(inspect_tweet(url, opts), ensure_ascii=False, indent=2))
            else:
                for item in download_tweet(url, opts, args.max_height, args.index, args.audio_only):
                    height = f"{item['height']}p" if item["height"] else "音訊"
                    print(f"{item['file']}  {height}  {item['size_mb']} MB")
        except TweetVideoError as exc:
            failed += 1
            print(f"失敗：{url}\n  {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
