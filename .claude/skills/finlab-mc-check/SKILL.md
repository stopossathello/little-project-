---
name: finlab-mc-check
description: 對 finlab 回測做蒙地卡羅檢查，包含日報酬區塊重抽樣、隨機剔除交易、同換手率隨機選股對照，工具是使用者 Google Drive 裡的 finlab_v4/mc_check.py。使用時機：使用者說「跑蒙地卡羅」「MC 檢查」「重抽樣」「bootstrap」「隨機選股對照」「剔除交易」；貼出 finlab sim() 報告或年化、MDD、夏普，問能不能上線、要不要加碼、實單最大回落可能多深、績效是不是運氣；討論策略A-週、策略B、策略C、turbo_b_v4 或其他 finlab 策略的穩健性。使用者沒說出「蒙地卡羅」，但正在評估某個 finlab 策略的風險或可信度時，也要使用這個 skill 並主動提出檢查。只問蒙地卡羅的概念、沒有具體策略要檢查時不需要。
---

# finlab 蒙地卡羅檢查

一次回測只是歷史走過的一條路徑。這個 skill 把使用者的 finlab 回測重抽樣或重跑幾十到幾千次，從績效的分布回答三個問題：

| 函式 | 回答的問題 |
|---|---|
| `mc_bootstrap(report)` | 年化、MDD、夏普可能落在什麼範圍（日報酬以 20 日為一段做區塊重抽樣） |
| `mc_drop_trades(report, position, sim_kwargs)` | 隨機剔除 20% 交易後重跑，績效會不會崩 |
| `mc_random_picks(report, position, universe, sim_kwargs)` | 同檔數、同換手率的隨機選股，報酬來自選股還是來自行情 |

工具程式在使用者 Drive 的 `finlab_v4/mc_check.py`（file id `1iW2b_reurSlvL5rddVWj4lu9-_iHO-Av`），本 skill 的 `scripts/mc_check.py` 是同一份。使用者可能改過 Drive 版，兩者不同時以 Drive 為準。

## 1. 確認策略，備齊三個輸入

三個輸入都要跟原回測完全一致，否則模擬結果跟原報告比較沒有意義：

- `position`：丟進 `sim()` 的第一個參數，包含 `.loc[...]` 切片
- `sim_kwargs`：`sim()` 的其餘參數（resample、trade_at_price、fee_ratio、trail_stop 等）
- `universe`：布林表，只放流動性與基本門檻（成交量、成交金額、股價、排除處置股），不放選股因子。隨機選股對照要回答「選股因子有沒有用」，universe 混進因子就會把答案污染。

使用者的既有策略整理在 `references/strategies.md`，內容有 Drive 檔案 id、變數名稱、建議的 universe、已經做過的穩健性檢查。先讀這份。策略會改版，能用 Google Drive 工具時，下載原始檔確認變數名稱還在（下載結果是 base64，筆記本是 JSON）。

新策略或使用者直接貼程式碼時，從程式碼找出這三樣。找不到流動性條件時，用 `(data.get('price:成交金額').average(20) > 1e8) & (close > 10)`，並告訴使用者這是預設值。

## 2. 決定執行方式

在有 shell 的環境先檢查能不能直接跑：

```bash
python -c "import finlab" 2>/dev/null || pip install -q finlab
test -n "$FINLAB_API_TOKEN" && echo token-ok
curl -s -o /dev/null -w "%{http_code}\n" --max-time 10 https://ai.finlab.tw/
```

- 套件可用、token 存在、網域有回應（狀態碼不是 000）：走第 3B 節直接執行
- 任何一項不通過，或是在沒有 shell 的對話裡：走第 3A 節產生 Colab cell，並用一句話說明卡在哪裡。要讓 Claude 直接跑，使用者得在雲端環境設定加上環境變數 `FINLAB_API_TOKEN`，網路開放 `ai.finlab.tw`、`finlab.finance`、`r2.finlab.finance`、`www.finlab.finance`。token 不要請使用者貼進對話。

## 3A. 產生 Colab cell

給使用者兩段程式碼。第一段取代原本的 `report = sim(...)`，把參數抽成 `sim_kwargs`，確保蒙地卡羅重跑時用的參數跟原回測相同：

```python
sim_kwargs = dict(resample='W', trade_at_price='open', fee_ratio=1.425/1000*0.28)   # 照原本 sim() 的參數
pos_mc = position.loc['2020':]                                                      # 原本丟進 sim() 的 position
universe = cond_vol                                                                 # 流動性門檻
report = sim(pos_mc, **sim_kwargs)
```

第二段接在後面：

```python
# ===== 蒙地卡羅檢查 =====
from google.colab import drive
drive.mount('/content/drive')
import sys
sys.path.append('/content/drive/MyDrive/finlab_v4')
from mc_check import mc_bootstrap, mc_drop_trades, mc_random_picks

mc_bootstrap(report)                                     # 全期間分布
mc_bootstrap(report, horizon=252)                        # 未來一年
mc_bootstrap(report, cagr_keep=0.6)                      # 年化打六折
mc_drop_trades(report, pos_mc, sim_kwargs)               # 隨機剔除 20% 交易，重跑 30 次
mc_random_picks(report, pos_mc, universe, sim_kwargs)    # 隨機選股對照，重跑 30 次
```

變數名稱一律換成該策略實際的名稱，筆記本裡已經有 `sim_kwargs` 的（例如策略C）就直接用。附上這幾點說明：

- 後兩個函式每次都重跑一次完整的 `sim()`，n=30 就是 30 次回測的時間；想先試跑可以加 `n=10`
- 出現 `ModuleNotFoundError: mc_check` 代表 Drive 沒有檔案或路徑不同，把 `scripts/mc_check.py` 給使用者上傳到 finlab_v4
- Drive 上的 mc_check.py 改過之後，要重新啟動執行階段才會載入新版
- 跑完把印出來的表格整段貼回來

## 3B. 直接執行

1. 用 Drive 工具下載策略原始檔，把 base64 寫進檔案後用 `base64 -d` 解碼。筆記本用 `python scripts/nb_to_py.py 策略.ipynb > strategy.py` 抽出程式碼 cell，它會略過 `%pip`、`!` 指令、`display(...)` 和下單用的 cell
2. 依賴同資料夾模組的策略（turbo_b_v4 需要 broker_features.py 和它的快取 csv）一併下載到同一目錄
3. 在 strategy.py 尾端接上第 3A 節的五個呼叫，從 `scripts/mc_check.py` import，然後執行
4. finlab VIP 每天的資料用量有上限（筆記本輸出顯示 5000 MB），同一個 session 重複跑會用到快取

## 4. 解讀結果

使用者貼回輸出，或直接執行完成之後，照這個結構回覆：

**數字摘要**：一張表列出三種檢查的原始值、最差5%、中位數（年化、MDD、夏普）。

**逐項判讀**。以下門檻是經驗判斷，回覆時要講明是判斷：

- 區塊重抽樣：資金控管以「最差5%」那欄的 MDD 為準。原始 MDD 比中位數淺，代表歷史路徑偏幸運。MDD 超過 -50% 的機率不低時，算出曝險要縮到幾成，最差5% 的回落才落在使用者能承受的範圍（曝險減半，回落大約減半）。
- `horizon=252`：一年內的最差情況和虧損機率，也就是實單第一年最可能碰到的數字。
- `cagr_keep=0.6`：使用者自己預期實單年化會打 6 到 7 折，這張表是那個情境下的回落。
- 剔除交易：看年化中位數是原始的幾成。九成以上算穩；掉到一半左右代表報酬集中在少數幾筆，建議回頭看 `report.trades` 裡獲利最大的幾筆交易。
- 隨機選股：看隨機組合的中位數離原策略多遠，以及追上的次數與 p 值。隨機組合的中位數已經有原策略一半以上的年化，代表大部分報酬來自行情或 universe 本身。n=30 時 p 值最小只到約 0.03，想更有把握就把 n 加到 50 到 100。

**這個檢查看不到的事**：重抽樣的材料只有回測期間的報酬。使用者多數策略從 2020 年開始回測，期間以動能行情為主（策略A 在 2007 到 2018 年是虧損的），所以要搭配他已經在做的分期間、walk-forward、資料時效檢查，不能只靠蒙地卡羅下結論。

**下一步建議**：要具體到部位或參數，例如曝險比例、持股檔數，或是哪個檢查值得加大 n 再跑一次。

## 方法上的限制

使用者問到，或結果看起來異常時說明：

- 沒有做交易順序重排：投組同時持有多檔，交易在時間上互相重疊，打亂順序沒有意義
- `mc_random_picks` 一律等權。原策略是浮點權重時（策略C 的單位數、turbo_b_v4 的流動性上限權重），比較結果會混進權重方式的差異
- `sim_kwargs` 裡的停損停利（例如 trail_stop）也會套用在隨機組合
- `mc_drop_trades` 遇到浮點權重時，會把剩下的部位等比例放大來維持總曝險，可能超過原本的流動性上限
- 持股只有 3 到 5 檔的策略，剔除交易和隨機選股的結果變異會很大，n 要加大
