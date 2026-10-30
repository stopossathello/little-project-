# X (Twitter) 影片下載 agent

貼推文連結或用自然語言描述，由 Claude 判斷要查詢哪些推文、用什麼畫質下載。底層用 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 抓影片。

## 安裝

需要 Python 3.10 以上。ffmpeg 可裝可不裝：沒有 ffmpeg 一樣能抓有聲音的 mp4，只有「只抓聲音」需要它。

```bash
cd twitter-video-agent
pip install -r requirements.txt
# 選用：macOS: brew install ffmpeg / Ubuntu: sudo apt install ffmpeg / Windows: winget install Gyan.FFmpeg
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

### Telegram bot（傳連結給 bot，影片自動傳回來）

不需要 Anthropic API key。bot 跑在你的電腦上，電腦開著、bot 視窗開著才會回應。

**Windows 第一次設定**

1. 安裝 Python：到 https://www.python.org/downloads/ 下載，安裝畫面第一頁勾選 **Add python.exe to PATH** 再按 Install Now。
2. 下載程式：打開 https://github.com/stopossathello/little-project-/archive/refs/heads/claude/twitter-video-agent.zip ，解壓縮後進入 `twitter-video-agent` 資料夾。
3. 在 Telegram 搜尋 **@BotFather**，傳 `/newbot`，照指示幫 bot 取名字和帳號（帳號要以 `bot` 結尾），最後會拿到一串 token，長得像 `123456789:AAH...`。
4. 雙擊 `start_bot.bat`。第一次會自動安裝套件，接著要你貼上 token（在黑色視窗按滑鼠右鍵就是貼上）。
5. 視窗顯示 bot 的連結後，用 Telegram 打開它按「開始」。視窗會問「這是你本人嗎？」，輸入 `y` 按 Enter。
6. 看到「bot 已啟動」就完成了，視窗保持開著即可。設定存在 `bot.env`，之後雙擊 `start_bot.bat` 會直接啟動。

**macOS / Linux**：在終端機進入資料夾，執行 `pip3 install -r requirements.txt` 再執行 `python3 telegram_bot.py`，設定流程相同。

**使用**：把推文連結傳給 bot，影片會直接傳回聊天室。從 X App 按「分享」再「複製連結」貼上即可，一則訊息可以貼多個連結。

**開機自動啟動（Windows）**

1. 按 `Win + R`，輸入 `shell:startup` 按 Enter，會打開「啟動」資料夾。
2. 在 `start_bot.bat` 按右鍵，選「顯示其他選項」再選「建立捷徑」，把捷徑拖進「啟動」資料夾。
3. 到「設定 → 系統 → 電源」，把接上電源時的睡眠設成「永不」，否則電腦睡著後 bot 就不會回應。

要換 token 或換帳號：執行 `start_bot.bat --setup`，或刪掉 `bot.env` 再雙擊 `start_bot.bat`。也可以改用環境變數 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_ALLOWED_USERS`（多個 user ID 用逗號分隔）。

訊息裡可以加的指示：

| 寫法 | 效果 |
|---|---|
| `720p` | 畫質上限 720p |
| `音訊` 或 `聲音` | 只抓聲音，傳 m4a |
| 網址結尾 `/video/2` | 推文有多支影片時只抓第 2 支 |

Telegram 限制 bot 上傳的檔案不能超過 50 MB。影片超過時，bot 會自動改抓較低畫質，並在聊天室說明。最低畫質還是超過時，檔案會存在電腦的 `downloads/` 資料夾，聊天室會回報路徑。其他檔案上傳完就刪除，不佔電腦空間。

bot 的參數：`--max-height 720`（預設畫質上限），以及下方的 `--cookies-from-browser` 等共用參數。

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
python -m unittest test_downloader test_telegram_bot
```
