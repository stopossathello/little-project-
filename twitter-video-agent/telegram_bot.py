"""Telegram bot：把推文連結傳給 bot，它下載影片後傳回聊天室。

    export TELEGRAM_BOT_TOKEN=123456789:AA...
    export TELEGRAM_ALLOWED_USERS=你的 user ID（多個用逗號分隔）
    python telegram_bot.py

訊息裡可以加「720p」限制畫質，加「音訊」只抓聲音。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from telegram import LinkPreviewOptions, Message, MessageEntity, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, Defaults, MessageHandler, filters

import downloader as dl

log = logging.getLogger("telegram_bot")

# 檔案超過上傳上限時，依序改抓這些畫質
FALLBACK_HEIGHTS = [720, 540, 480, 360, 240]

# 網址只取 ASCII 字元，所以中文字或全形標點緊貼在網址前後也能正確切開
_LINK = re.compile(
    r"(?<![A-Za-z0-9_.])(?:https?://)?(?:(?:www|mobile|m)\.)?"
    r"(?:x|twitter|fxtwitter|vxtwitter|fixupx|fixvx)\.com/[A-Za-z0-9\-._~:/?#@!$&'()*+,;=%]+",
    re.IGNORECASE,
)
_TRAILING = ".,，。、!！?？)）]」』】>"
_HEIGHT = re.compile(r"(?<!\d)(\d{3,4})\s*p\b", re.IGNORECASE)
_AUDIO_WORDS = ("音訊", "聲音", "音檔", "audio", "mp3", "m4a")

HELP_TEXT = """把推文連結傳給我，我會下載影片傳回來。

可以一次貼多個連結。訊息裡加上：
• 720p：畫質上限 720p
• 音訊：只抓聲音

你的 Telegram user ID：{user_id}"""


@dataclass(frozen=True)
class BotConfig:
    allowed_users: frozenset[int]
    download: dl.DownloadOptions
    max_height: int | None
    upload_limit_mb: float


def find_tweets(text: str, extra_urls: list[str] | None = None) -> list[dl.TweetRef]:
    """從訊息文字和隱藏連結裡找出推文網址，去除重複，保持原本順序。"""
    candidates = [m.rstrip(_TRAILING) for m in _LINK.findall(text)] + list(extra_urls or [])
    refs: dict[tuple[str, int | None], dl.TweetRef] = {}
    for raw in candidates:
        try:
            ref = dl.parse_tweet_url(raw)
        except dl.TweetVideoError:
            continue
        refs.setdefault((ref.url, ref.index), ref)
    return list(refs.values())


def parse_options(text: str) -> tuple[int | None, bool]:
    """回傳 (畫質上限, 是否只抓聲音)。網址本身的內容不列入判斷。"""
    plain = _LINK.sub(" ", text)
    match = _HEIGHT.search(plain)
    audio_only = any(word in plain.lower() for word in _AUDIO_WORDS)
    return (int(match[1]) if match else None), audio_only


def fetch_for_upload(
    ref: dl.TweetRef,
    opts: dl.DownloadOptions,
    max_height: int | None,
    audio_only: bool,
    limit_mb: float,
    save_dir: Path,
) -> tuple[list[dict], list[str]]:
    """下載推文影片，確保每個要上傳的檔案都在上限內。回傳 (可上傳的檔案, 給使用者的說明)。"""
    sendable, notes = [], []
    for item in dl.download_tweet(ref.url, opts, max_height, ref.index, audio_only):
        if item["size_mb"] <= limit_mb:
            sendable.append(item)
            continue
        smaller = None if audio_only else _smaller_version(ref, opts, item, limit_mb)
        if smaller:
            sendable.append(smaller)
            notes.append(
                f"第 {item['index']} 支 {item['height']}p 有 {item['size_mb']} MB，"
                f"超過 {limit_mb:g} MB 上傳上限，改傳 {smaller['height']}p"
            )
            continue
        save_dir.mkdir(parents=True, exist_ok=True)
        dest = save_dir / Path(item["file"]).name
        shutil.move(item["file"], dest)
        notes.append(
            f"第 {item['index']} 支有 {item['size_mb']} MB，降到最低畫質仍超過 {limit_mb:g} MB 上傳上限，"
            f"已存到電腦：{dest.resolve()}"
        )
    return sendable, notes


def _smaller_version(ref: dl.TweetRef, opts: dl.DownloadOptions, item: dict, limit_mb: float) -> dict | None:
    current = item["height"] or 0
    for height in FALLBACK_HEIGHTS:
        if current and height >= current:
            continue
        # 每種畫質放不同資料夾，否則檔名相同，yt-dlp 會當成已下載而跳過
        attempt = dl.download_tweet(ref.url, replace(opts, out_dir=opts.out_dir / f"{height}p"), height, item["index"])
        candidate = attempt[0]
        if candidate["size_mb"] <= limit_mb:
            return candidate
        if not candidate["height"] or candidate["height"] >= current:
            return None  # 沒有更低的畫質可選
        current = candidate["height"]
    return None


def _caption(ref: dl.TweetRef, item: dict) -> str:
    quality = f"{item['height']}p" if item.get("height") else "音訊"
    who = f"@{item['uploader_id']} " if item.get("uploader_id") else ""
    return f"{who}{quality}，{item['size_mb']} MB\n{ref.url}"


async def _send(message: Message, ref: dl.TweetRef, item: dict, audio_only: bool) -> None:
    duration = int(item["duration_sec"]) if item.get("duration_sec") else None
    with open(item["file"], "rb") as fh:
        if audio_only:
            await message.reply_chat_action(ChatAction.UPLOAD_VOICE)
            await message.reply_audio(fh, caption=_caption(ref, item), duration=duration,
                                      filename=Path(item["file"]).name)
        else:
            await message.reply_chat_action(ChatAction.UPLOAD_VIDEO)
            await message.reply_video(fh, caption=_caption(ref, item), duration=duration,
                                      width=item.get("width"), height=item.get("height"),
                                      supports_streaming=True, filename=Path(item["file"]).name)


async def _process(message: Message, ref: dl.TweetRef, max_height: int | None, audio_only: bool,
                   config: BotConfig) -> None:
    status = await message.reply_text(f"下載中：{ref.url}")
    with tempfile.TemporaryDirectory(prefix="tweet-video-") as tmp:
        opts = replace(config.download, out_dir=Path(tmp))
        try:
            files, notes = await asyncio.to_thread(
                fetch_for_upload, ref, opts, max_height, audio_only,
                config.upload_limit_mb, config.download.out_dir,
            )
        except dl.TweetVideoError as exc:
            await status.edit_text(f"失敗：{ref.url}\n{exc}")
            return
        try:
            for item in files:
                await _send(message, ref, item, audio_only)
        except TelegramError as exc:
            log.warning("上傳失敗 %s: %s", ref.url, exc)
            notes.append(f"上傳到 Telegram 失敗：{exc}")
    if notes:
        await status.edit_text(f"{ref.url}\n" + "\n".join(notes))
    else:
        await status.delete()


def _config(context: ContextTypes.DEFAULT_TYPE) -> BotConfig:
    return context.application.bot_data["config"]


async def _reject_if_not_allowed(update: Update, config: BotConfig) -> bool:
    user = update.effective_user
    if user and user.id in config.allowed_users:
        return False
    user_id = user.id if user else "未知"
    log.info("拒絕未授權的使用者 %s", user_id)
    if not config.allowed_users:
        await update.effective_message.reply_text(
            f"bot 還沒設定可以使用的帳號。\n你的 user ID 是 {user_id}，"
            f"請設定 TELEGRAM_ALLOWED_USERS={user_id} 後重新啟動 bot。"
        )
    else:
        await update.effective_message.reply_text(f"你沒有使用這個 bot 的權限。（user ID：{user_id}）")
    return True


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT.format(user_id=update.effective_user.id))


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _config(context)
    if await _reject_if_not_allowed(update, config):
        return
    message = update.effective_message
    text = message.text or message.caption or ""
    hidden_links = [
        entity.url
        for entity in (*(message.entities or ()), *(message.caption_entities or ()))
        if entity.type == MessageEntity.TEXT_LINK and entity.url
    ]
    refs = find_tweets(text, hidden_links)
    if not refs:
        await message.reply_text("沒有找到推文連結。請傳 https://x.com/<帳號>/status/<數字> 這種網址。")
        return
    max_height, audio_only = parse_options(text)
    for ref in refs:
        await _process(message, ref, max_height or config.max_height, audio_only, config)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("處理訊息時發生錯誤", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(f"發生錯誤：{context.error}")
        except TelegramError:
            pass


def _parse_user_ids(raw: str) -> frozenset[int]:
    ids = set()
    for part in re.split(r"[,\s]+", raw.strip()):
        if part:
            if not part.lstrip("-").isdigit():
                raise SystemExit(f"TELEGRAM_ALLOWED_USERS 只能填數字 user ID：{part}")
            ids.add(int(part))
    return frozenset(ids)


def build_application(token: str, config: BotConfig, base_url: str | None = None) -> Application:
    builder = (
        Application.builder()
        .token(token)
        .defaults(Defaults(link_preview_options=LinkPreviewOptions(is_disabled=True)))
        .media_write_timeout(300)
        .read_timeout(60)
    )
    if base_url:
        builder = builder.base_url(base_url)
    app = builder.build()
    app.bot_data["config"] = config
    app.add_handler(CommandHandler(["start", "help", "id"], on_start))
    app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="傳推文連結給 Telegram bot，自動下載影片並傳回")
    parser.add_argument("--max-height", type=int, help="預設畫質上限，訊息裡寫的畫質優先")
    parser.add_argument("--upload-limit-mb", type=float, default=50,
                        help="單一檔案上傳上限，Telegram 官方 Bot API 是 50 MB")
    dl.add_cookie_args(parser)
    args = parser.parse_args(argv)

    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("請先設定 TELEGRAM_BOT_TOKEN（向 @BotFather 申請）。", file=sys.stderr)
        return 1
    allowed = _parse_user_ids(os.environ.get("TELEGRAM_ALLOWED_USERS", ""))
    if not allowed:
        log.warning("沒有設定 TELEGRAM_ALLOWED_USERS，所有人都無法下載。傳訊息給 bot 會回覆你的 user ID。")

    config = BotConfig(
        allowed_users=allowed,
        download=dl.options_from_args(args),
        max_height=args.max_height,
        upload_limit_mb=args.upload_limit_mb,
    )
    app = build_application(token, config, os.environ.get("TELEGRAM_API_BASE_URL"))
    log.info("bot 已啟動，按 Ctrl+C 停止")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0


if __name__ == "__main__":
    sys.exit(main())
