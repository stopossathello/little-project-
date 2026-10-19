# 使用者的 finlab 策略對照表

2026-10 從 Google Drive 原始檔整理。策略會改版，使用前用 Drive 工具確認變數名稱還在。

## Drive 位置

| 項目 | id | 備註 |
|---|---|---|
| Colab 筆記本資料夾 | `1XIxnRog7Pe7itK7lPY0GAk_XijpXTk2u` | 策略A-週、策略B、策略C |
| finlab_v4 資料夾 | `14-cWmYc-gnsGtetJd4P_QHlSE2eHDpaO` | 在「我的雲端硬碟」根目錄，Colab 路徑 `/content/drive/MyDrive/finlab_v4` |
| mc_check.py | `1iW2b_reurSlvL5rddVWj4lu9-_iHO-Av` | 放在 finlab_v4 |

Colab 筆記本讀 Colab secret `FINLAB_API_TOKEN` 登入 finlab。

## 三個輸入對照

| 策略 | position | sim_kwargs | universe | 持股型態 |
|---|---|---|---|---|
| 策略C 第一格 | `pos_bt` | 筆記本已有 `sim_kwargs` | `liq1` | 浮點單位數 1 到 3 |
| 策略C 第二格 TOP2 | `position.loc[START:]` | `dict(resample='W', trade_at_price='open')` | `liquid` | 布林 5 檔 |
| 策略B | `position.loc[position.index >= start_date]` | `dict(trade_at_price='open', fee_ratio=1.425/1000*0.28)` | `condition3 & condition7` | 布林 20 檔 |
| turbo_b_v4.py | `weights.loc[start_date:]` | `dict(trade_at_price=TRADE_AT, fee_ratio=1.425/1000*0.28)` | `condition3 & condition7 & condition10` | 浮點權重 |
| 策略A-週 | `position` | `dict(resample='W', trade_at_price='open', trail_stop=0.2)` | `cond_vol` | 布林 3 檔 |

## 各策略細節

### 策略C（Colab，id `12ISwmFzK3_0Jn8cldveWPi3-UYdN9Uux`）

- 第一格是「三子策略投票 tier3」：`pos_bt` 由三個子策略相加，分別是大戶因子 7 檔（`sel_A`）、五因子 5 檔且流動性 1.5 億（`sel_B`）、五因子 7 檔（`sel_E`），所以值是 1 到 3 的單位數
- `sim_kwargs = dict(resample='W', trade_at_price='close', upload=False, name='三子策略投票_tier3')`，資料夠新時會再加 `live_performance_start`
- `liq1` = 20 日均成交金額 > 1 億且收盤 > 10
- 第二格 TOP2 存在 `report2`，`liquid` 是同樣的 1 億門檻
- 已做過：walk-forward，註解寫 TOP2 樣本外衰退最重

### 策略B（Colab，id `1LpKssWnbstp2tM5cdic-G7DOloSWEV25`）營收股價雙渦輪-B 優化版

- position 的 index 是營收公告截止日，沒有 resample
- `trail_stop=0.25` 在程式碼裡被註解掉
- `condition3` = 5 日均量 > 500 張，`condition7` = 排除處置股
- 已做過：參數平台檢查（註解寫參數都在平台區）；同邏輯 2014 到 2019 夏普只有約 1.5；註解預期實單夏普 1.5 到 1.8、年化打 6 到 7 折

### turbo_b_v4.py（finlab_v4，id `1E0YPr1LGvJhRlfY8RTtl2O-hd1O7Xoll`）雙渦輪-B v4 加分點濾網

- 依賴同資料夾的 `broker_features.py`（id `1g0QpHXIbKxRW4awZRKfADq37ssdM0615`）和 `broker_feat_sparse.csv`（id `1eteo3MLM1o5XbXuPFLw-AbKoRgLl1brs`）
- `weights` 是等權後再套流動性上限（單檔 ≤ P × 20 日均成交金額 ÷ FUND），總和可能小於 1
- `TRADE_AT = 'close'`；`condition10` = 5 日均成交金額排名前 30%
- 已做過：隨機短沖標籤的安慰劑測試，結果寫在 research_log.html 第八節（這份檔案不在 Drive）

### 策略A-週（Colab，id `1jzkF0kYcJQpip7rcJvaWjwzPTL7FQ7ba`）融資過熱過濾動能 積極版

- `position` 已經 `.loc['2020':]`，3 檔，每週換股
- `cond_vol` = 20 日均量 > 1000 張
- 已做過：分期間檢查，2007 到 2018 年化 -8.5%、夏普 -0.04，註解把它定位成押注 2019 年後行情延續；集保資料晚一週的敏感度，2020 年後年化從 133.4% 掉到 62.9%
- 只有 3 檔，剔除交易和隨機選股的變異會很大，n 建議加到 50 以上
