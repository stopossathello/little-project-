"""凱基-三多 分點：過去三年「大額買進 → 單次大額賣出」勝率（排除 ETF）與目前大額庫存。

交易定義（可用參數調整）：
- 大額買進日：該分點單日對單一個股淨買超金額 >= BIG_AMOUNT
- 大額賣出日：該分點單日對單一個股淨賣超金額 >= BIG_AMOUNT
- 第一次大額買進開倉；之後再出現大額買進就加碼（加權平均成本）
- 之後第一次大額賣出就整筆平倉，算一筆交易
- 勝：賣出均價 > 買進加權均價（另列扣手續費 0.1425%x2 + 證交稅 0.3% 的版本）
- 價格優先用分點當日成交均價（金額/股數），沒有金額欄位時改用收盤價
- 排除 ETF：代號 00 開頭，以及非 4 碼的商品（權證、ETN 等）
"""

import os
import sys

import pandas as pd
from finlab import data

BRANCH_KEYWORDS = ("凱基", "三多")
YEARS = 3
BIG_AMOUNT = float(os.environ.get("BIG_AMOUNT", 10_000_000))  # 預設 1,000 萬
FEE_RATE = 0.001425 * 2 + 0.003
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def pick(cols, *cands):
    for c in cands:
        if c in cols:
            return c
    return None


def load_branch_rows():
    bt = data.get("broker_transactions")
    bt = bt.reset_index()
    print("broker_transactions 欄位:", list(bt.columns))
    print(bt.head(3).to_string())

    cols = set(bt.columns)
    c_broker = pick(cols, "broker", "broker_name", "券商", "券商分點", "分點", "證券商")
    if c_broker is None:
        # 找出字串欄位裡含「三多」的那一欄
        for c in bt.columns:
            if bt[c].dtype == object and bt[c].astype(str).str.contains("三多").any():
                c_broker = c
                break
    if c_broker is None:
        sys.exit("找不到分點名稱欄位，請看上面印出的欄位調整 pick()")

    names = bt[c_broker].astype(str)
    mask = names.str.contains(BRANCH_KEYWORDS[0]) & names.str.contains(BRANCH_KEYWORDS[1])
    matched = sorted(names[mask].unique())
    print("符合的分點:", matched)
    if not matched:
        # 名稱欄只有代號時，嘗試用 broker_mapping 對照
        sys.exit("沒有名稱同時含「凱基」「三多」的分點，請確認分點欄位內容")
    return bt[mask].copy()


def normalize(df):
    cols = set(df.columns)
    c_date = pick(cols, "date", "日期")
    c_sid = pick(cols, "stock_id", "symbol", "證券代號")
    c_buy = pick(cols, "buy", "買進股數", "buy_volume", "買進")
    c_sell = pick(cols, "sell", "賣出股數", "sell_volume", "賣出")
    c_buy_amt = pick(cols, "buy_amount", "買進金額", "buy_value")
    c_sell_amt = pick(cols, "sell_amount", "賣出金額", "sell_value")
    c_price = pick(cols, "price", "成交價", "價格")
    if not all([c_date, c_sid, c_buy, c_sell]):
        sys.exit(f"缺少必要欄位 date/stock_id/buy/sell: {sorted(cols)}")

    out = pd.DataFrame({
        "date": pd.to_datetime(df[c_date]),
        "stock_id": df[c_sid].astype(str).str.strip(),
        "buy": pd.to_numeric(df[c_buy], errors="coerce").fillna(0),
        "sell": pd.to_numeric(df[c_sell], errors="coerce").fillna(0),
    })
    if c_buy_amt and c_sell_amt:
        out["buy_amt"] = pd.to_numeric(df[c_buy_amt], errors="coerce").fillna(0)
        out["sell_amt"] = pd.to_numeric(df[c_sell_amt], errors="coerce").fillna(0)
    elif c_price:
        # 逐價位明細：股數 x 價位
        p = pd.to_numeric(df[c_price], errors="coerce")
        out["buy_amt"] = out["buy"] * p
        out["sell_amt"] = out["sell"] * p
    else:
        out["buy_amt"] = float("nan")
        out["sell_amt"] = float("nan")

    # 同一天同一檔可能有多列（逐價位），彙總成日資料
    daily = out.groupby(["date", "stock_id"], as_index=False).sum(min_count=1)
    return daily


def exclude_etf(df):
    sid = df["stock_id"]
    keep = sid.str.fullmatch(r"\d{4}") & ~sid.str.startswith("00")
    return df[keep]


def attach_prices(daily):
    close = data.get("price:收盤價")
    c = close.stack().rename("close").reset_index()
    c.columns = ["date", "stock_id", "close"]
    daily = daily.merge(c, on=["date", "stock_id"], how="left")

    # 分點均價；沒有金額時用收盤價
    daily["buy_px"] = (daily["buy_amt"] / daily["buy"]).where(daily["buy"] > 0)
    daily["sell_px"] = (daily["sell_amt"] / daily["sell"]).where(daily["sell"] > 0)
    daily["buy_px"] = daily["buy_px"].fillna(daily["close"])
    daily["sell_px"] = daily["sell_px"].fillna(daily["close"])

    net_sh = daily["buy"] - daily["sell"]
    amt = daily["buy_amt"] - daily["sell_amt"]
    daily["net_amt"] = amt.where(amt.notna(), net_sh * daily["close"])
    daily["net_sh"] = net_sh
    return daily, close


def run_trades(daily):
    trades, open_pos = [], []
    for sid, g in daily.sort_values("date").groupby("stock_id"):
        pos = None
        for r in g.itertuples(index=False):
            if r.net_amt >= BIG_AMOUNT:
                sh, px = r.net_sh, r.buy_px
                if pos is None:
                    pos = {"stock_id": sid, "entry_date": r.date, "shares": 0.0,
                           "cost": 0.0, "n_buys": 0}
                pos["shares"] += sh
                pos["cost"] += sh * px
                pos["n_buys"] += 1
                pos["last_buy"] = r.date
            elif r.net_amt <= -BIG_AMOUNT and pos is not None:
                avg = pos["cost"] / pos["shares"]
                ret = r.sell_px / avg - 1
                trades.append({
                    **{k: pos[k] for k in ("stock_id", "entry_date", "n_buys")},
                    "exit_date": r.date,
                    "hold_days": (r.date - pos["entry_date"]).days,
                    "avg_cost": avg, "exit_px": r.sell_px,
                    "buy_shares": pos["shares"], "exit_shares": -r.net_sh,
                    "ret": ret, "ret_net": ret - FEE_RATE,
                })
                pos = None
        if pos is not None:
            open_pos.append(pos)
    return pd.DataFrame(trades), open_pos


def main():
    rows = load_branch_rows()
    daily = normalize(rows)
    end = daily["date"].max()
    start = end - pd.DateOffset(years=YEARS)
    daily = exclude_etf(daily[daily["date"] > start])
    daily, close = attach_prices(daily)

    trades, open_pos = run_trades(daily)
    print(f"\n區間 {start.date()} ~ {end.date()}，大額門檻 {BIG_AMOUNT:,.0f} 元")
    if trades.empty:
        print("沒有完成的交易")
    else:
        n = len(trades)
        print(f"完成交易 {n} 筆，涉及 {trades['stock_id'].nunique()} 檔")
        print(f"勝率（未扣成本）{(trades['ret'] > 0).mean():.1%}")
        print(f"勝率（扣成本）  {(trades['ret_net'] > 0).mean():.1%}")
        print(f"平均報酬 {trades['ret'].mean():.2%}，中位數 {trades['ret'].median():.2%}")
        print(f"平均持有 {trades['hold_days'].mean():.0f} 天")
        trades.to_csv(os.path.join(OUT_DIR, "kgi_sanduo_trades.csv"), index=False,
                      encoding="utf-8-sig")

    # 目前大額庫存：大額買進後還沒出現大額賣出的部位
    last_close = close.ffill().iloc[-1]
    names = data.get("company_basic_info")[["stock_id", "公司簡稱"]].drop_duplicates("stock_id")
    names = names.set_index("stock_id")["公司簡稱"]
    inv = []
    for p in open_pos:
        # 開倉後到現在的所有淨買賣（含小額）也算進去，看實際剩多少
        g = daily[(daily["stock_id"] == p["stock_id"]) & (daily["date"] >= p["entry_date"])]
        px = last_close.get(p["stock_id"], float("nan"))
        avg = p["cost"] / p["shares"]
        inv.append({
            "stock_id": p["stock_id"], "name": names.get(p["stock_id"], ""),
            "entry_date": p["entry_date"].date(), "last_big_buy": p["last_buy"].date(),
            "big_buy_lots": round(p["shares"] / 1000),
            "net_lots_since_entry": round(g["net_sh"].sum() / 1000),
            "avg_cost": round(avg, 2), "last_close": px,
            "unrealized": px / avg - 1 if px == px else float("nan"),
            "market_value": g["net_sh"].sum() * px,
        })
    inv = pd.DataFrame(inv)
    if not inv.empty:
        inv = inv.sort_values("market_value", ascending=False)
        inv.to_csv(os.path.join(OUT_DIR, "kgi_sanduo_inventory.csv"), index=False,
                   encoding="utf-8-sig")
        pd.set_option("display.width", 200)
        print("\n目前大額庫存（依市值排序）:")
        print(inv.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
