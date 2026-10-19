# X (Twitter) 影片下載 agent

貼推文連結或用自然語言描述，由 Claude 判斷要查詢哪些推文、用什麼畫質下載。底層用 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 抓影片。

## 安裝

需要 Python 3.10 以上和 ffmpeg（合併影音、轉音訊用）。

```bash
cd twitter-video-agent
pip install -r requirements.txt
# macOS: brew install ffmpeg / Ubuntu: sudo apt install ffmpeg / Windows: winget install ffmpeg
```

agent 模式需要 Anthropic API key：

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## 使用方式

### agent 模式（自然語言）

```bash
# 一次性指令
python agent.py "抓這兩則的影片，720p 就好 https://x.com/SpaceX/status/1732824684683784516 https://x.com/xxx/status/123"

# 對話模式，可以接著問「剛剛抓了什麼」「第二支改成只要聲音」
python agent.py
```

agent 可以做的事：

| 工具 | 用途 |
|---|---|
| `inspect_tweet` | 查推文裡有幾支影片、長度、可用畫質 |
| `download_video` | 下載，可指定畫質上限、多支影片中的第幾支、只抓聲音 |
| `list_downloads` | 列出輸出資料夾裡已下載的檔案 |

### 直接下載（不用 API key）

```bash
python downloader.py https://x.com/SpaceX/status/1732824684683784516               # 最高畫質
python downloader.py https://x.com/SpaceX/status/1732824684683784516 --max-height 720
python downloader.py https://x.com/user/status/123/video/2                          # 多支影片只抓第 2 支
python downloader.py https://x.com/user/status/123 --audio-only                     # 只要聲音（m4a）
python downloader.py https://x.com/user/status/123 --info                           # 只看資訊不下載
```

### 共用參數

| 參數 | 說明 |
|---|---|
| `--out DIR` | 輸出資料夾，預設 `./downloads` |
| `--cookies cookies.txt` | Netscape 格式的 cookies 檔，下載需要登入的推文（敏感內容、私人帳號）時使用 |
| `--cookies-from-browser chrome` | 直接讀瀏覽器的 X 登入狀態，支援 chrome、firefox、edge、safari 等 |

檔名格式為 `帳號_推文ID_媒體ID.mp4`，只抓聲音時是 `..._audio.m4a`。

## 支援的網址

`x.com`、`twitter.com`、`mobile.twitter.com`，以及 `fxtwitter.com`、`vxtwitter.com`、`fixupx.com` 這類轉嵌入網址。其他網站的連結會直接拒絕，推文裡夾帶的外部連結（例如 YouTube）也不會被下載。

## 設定

- 模型：`claude-opus-5-5`，effort 設為 `medium`，可在 `agent.py` 開頭修改 `MODEL`。
- 已開啟伺服器端 fallback（`fallbacks="default"`）：模型拒絕請求時，API 會自動改由其他模型接手。不需要的話刪掉 `betas` 和 `fallbacks` 兩行。
- 單輪對話最多呼叫工具 30 次（`MAX_ITERATIONS`）。

## 已知限制

- 無法抓整個帳號的時間軸，一次只處理指定的推文。
- X 改動網站時 yt-dlp 可能暫時失效，先執行 `pip install -U yt-dlp` 更新。
- 下載的影片請遵守著作權與 X 的使用條款。

## 測試

```bash
python -m unittest test_downloader
```
