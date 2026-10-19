"""用自然語言操作的 X (Twitter) 影片下載 agent，由 Claude 決定要查詢或下載哪些推文。

    python agent.py                       # 對話模式
    python agent.py "抓這兩則的影片，720p 就好 https://x.com/... https://x.com/..."
"""

from __future__ import annotations

import argparse
import json
import sys

import anthropic
from anthropic import beta_tool
from anthropic.lib.tools import ToolError

import downloader as dl

MODEL = "claude-opus-5-5"
MAX_ITERATIONS = 30

SYSTEM_PROMPT = """你是下載 X（Twitter）推文影片的助理，工具在使用者自己的電腦上執行，檔案會存到使用者指定的資料夾。

工作方式：
- 使用者給推文連結時，先用 inspect_tweet 確認有幾支影片、長度和可用畫質，再用 download_video 下載。使用者要求已經很明確（例如「直接抓 720p」）時可以跳過查詢直接下載。
- 使用者指定畫質就傳 max_height（例如 720）；只要聲音就設 audio_only。推文有多支影片而使用者只要其中一支時，用 video_index 指定，從 1 開始。網址結尾的 /video/2 代表第 2 支。
- 一次給多個連結時逐一處理，某一則失敗就記下原因繼續處理下一則，最後一起回報。
- 工具回傳錯誤時照實說明原因，不要猜測或重試同樣的參數。需要登入才看得到的推文（敏感內容、私人帳號），請使用者加上 --cookies 或 --cookies-from-browser 重新啟動。
- 只處理 x.com / twitter.com 的推文連結。其他網站的連結說明不支援即可。

回覆用繁體中文（台灣用語），簡短列出每個檔案的路徑、畫質、大小，失敗的列出原因。不要寒暄或客套話。"""


def build_tools(opts: dl.DownloadOptions) -> list:
    @beta_tool
    def inspect_tweet(url: str) -> str:
        """查詢一則推文裡有哪些影片，不下載。回傳帳號、推文內文、每支影片的長度與可用畫質。

        Args:
            url: 推文網址，例如 https://x.com/<帳號>/status/<數字>。
        """
        try:
            return json.dumps(dl.inspect_tweet(url, opts), ensure_ascii=False)
        except dl.TweetVideoError as exc:
            raise ToolError(str(exc)) from exc

    @beta_tool
    def download_video(
        url: str,
        max_height: int | None = None,
        video_index: int | None = None,
        audio_only: bool = False,
    ) -> str:
        """下載推文裡的影片，回傳每個檔案的路徑、畫質（高度）、長度和大小。

        Args:
            url: 推文網址。
            max_height: 畫質上限（像素高度，例如 720）。不填就下載最高畫質。
            video_index: 推文有多支影片時只下載第幾支，從 1 開始。不填就全部下載。
            audio_only: 設為 true 時只下載聲音，存成 m4a。
        """
        label = f"{url}" + (f" ≤{max_height}p" if max_height else "") + (" 音訊" if audio_only else "")
        print(f"  [下載中] {label}", file=sys.stderr, flush=True)
        try:
            files = dl.download_tweet(url, opts, max_height, video_index, audio_only)
        except dl.TweetVideoError as exc:
            raise ToolError(str(exc)) from exc
        return json.dumps({"url": url, "files": files}, ensure_ascii=False)

    @beta_tool
    def list_downloads() -> str:
        """列出輸出資料夾裡已經下載的檔案，新的排前面。"""
        return json.dumps(
            {"out_dir": str(opts.out_dir.resolve()), "files": dl.list_downloads(opts)},
            ensure_ascii=False,
        )

    return [inspect_tweet, download_video, list_downloads]


def run_turn(client: anthropic.Anthropic, tools: list, messages: list) -> None:
    """跑完一輪對話。messages 會同步更新，下一輪可以接著問。"""
    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        tools=tools,
        messages=messages,
        output_config={"effort": "medium"},
        # 模型拒絕請求時由伺服器自動改用其他模型接手
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        max_iterations=MAX_ITERATIONS,
    )
    last = None
    for message in runner:
        last = message
        # runner 自己保存的對話紀錄拿不到，這裡同步一份給下一輪用
        messages.append({"role": "assistant", "content": message.content})
        for block in message.content:
            if block.type == "text" and block.text.strip():
                print(block.text)
            elif block.type == "tool_use":
                print(f"  → {block.name} {json.dumps(block.input, ensure_ascii=False)}", file=sys.stderr)
        tool_response = runner.generate_tool_call_response()  # 有快取，工具不會重複執行
        if tool_response is not None:
            messages.append(tool_response)

    if last is not None and last.stop_reason == "refusal":
        print("這個請求被模型拒絕了。", file=sys.stderr)
    elif last is not None and last.stop_reason == "max_tokens":
        print("回覆超過長度上限被截斷。", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用自然語言下載 X (Twitter) 推文影片")
    parser.add_argument("request", nargs="*", help="要做的事，不填就進入對話模式")
    dl.add_cookie_args(parser)
    args = parser.parse_args(argv)

    tools = build_tools(dl.options_from_args(args))
    client = anthropic.Anthropic()
    messages: list = []

    def ask(text: str) -> bool:
        messages.append({"role": "user", "content": text})
        try:
            run_turn(client, tools, messages)
        except anthropic.AuthenticationError:
            print("API 驗證失敗，請設定 ANTHROPIC_API_KEY。", file=sys.stderr)
            return False
        except anthropic.APIStatusError as exc:
            print(f"API 錯誤 {exc.status_code}：{exc.message}", file=sys.stderr)
        except anthropic.APIConnectionError:
            print("連不到 Anthropic API，請檢查網路。", file=sys.stderr)
        return True

    if args.request:
        return 0 if ask(" ".join(args.request)) else 1

    print("貼上推文連結或描述要下載什麼，輸入 exit 離開。")
    while True:
        try:
            text = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if text.lower() in {"exit", "quit", "q"}:
            return 0
        if text and not ask(text):
            return 1


if __name__ == "__main__":
    sys.exit(main())
