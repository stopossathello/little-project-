# -*- coding: utf-8 -*-
"""
mc_check.py  finlab 回測的蒙地卡羅檢查
=====================================================================
接在 report = sim(...) 之後使用, 不改動原策略:

  1. mc_bootstrap(report)
       日報酬區塊重抽樣 -> 年化 / MDD / 夏普 的分布
       mc_bootstrap(report, horizon=252)       未來一年可能遇到的回落
       mc_bootstrap(report, cagr_keep=0.6)     實單年化打六折時的 MDD 分布
  2. mc_drop_trades(report, position, sim_kwargs)
       隨機剔除 20% 的交易後重跑 sim -> 績效是否集中在少數幾筆
  3. mc_random_picks(report, position, universe, sim_kwargs)
       同檔數、同換手率的隨機選股 -> 報酬來自選股, 還是來自行情

position / sim_kwargs 必須和原本丟進 sim() 的完全相同, 例如:
    sim_kwargs = dict(resample='W', trade_at_price='open', fee_ratio=1.425/1000*0.28)
    report = sim(position, **sim_kwargs)

不做「交易順序重排」: 多檔同時持有的投組, 交易在時間上互相重疊, 打亂順序沒有意義。
"""
import numpy as np
import pandas as pd

DAYS = 252
PCTS = [0.05, 0.25, 0.50, 0.75, 0.95]
PCT_NAMES = ['最差5%', '25%', '中位數', '75%', '最佳5%']
FMT = {'cagr': '{:+.1%}', 'mdd': '{:.1%}', 'sharpe': '{:.2f}'}
LABEL = {'cagr': '年化', 'mdd': 'MDD', 'sharpe': '夏普'}


# ---------- 共用 ----------
def _finlab_sim():
    from finlab.backtest import sim
    return sim


def _stats(eq, rf=0.02):
    """eq: (路徑數, 天數+1) 淨值矩陣, 第一欄為 1 -> 年化 / MDD / 夏普 (夏普公式同 finlab, 無風險利率 2%)"""
    T = eq.shape[1] - 1
    r = eq[:, 1:] / eq[:, :-1] - 1
    er = r - ((1 + rf) ** (1 / DAYS) - 1)
    return pd.DataFrame({
        'cagr': eq[:, -1] ** (DAYS / T) - 1,
        'mdd': (eq / np.maximum.accumulate(eq, axis=1) - 1).min(axis=1),
        'sharpe': er.mean(axis=1) / er.std(axis=1, ddof=1) * np.sqrt(DAYS),
    })


def _daily_returns(report):
    return report.creturn.pct_change().dropna().to_numpy()


def _report_stats(report, rf=0.02):
    r = _daily_returns(report)
    return _stats(np.r_[1.0, np.cumprod(1 + r)][None, :], rf).iloc[0]


def _table(sims, base=None):
    q = sims.quantile(PCTS)
    t = pd.DataFrame({name: [FMT[k].format(q[k].iloc[j]) for k in FMT]
                      for j, name in enumerate(PCT_NAMES)},
                     index=[LABEL[k] for k in FMT])
    if base is not None:
        t.insert(0, '原始', [FMT[k].format(base[k]) for k in FMT])
    return t


def _show(df):
    try:
        from IPython.display import display
        display(df)
    except ImportError:
        print(df.to_string())


def _shift_for_cagr(r, target):
    """找每日要扣掉的固定報酬 c, 讓 (r - c) 的年化剛好等於 target (二分法, 波動不變)"""
    goal = np.log1p(target) / DAYS
    lo, hi = -0.05, min(0.05, 1 + r.min() - 1e-9)
    for _ in range(100):
        c = (lo + hi) / 2
        if np.log1p(r - c).mean() > goal:
            lo = c
        else:
            hi = c
    return (lo + hi) / 2


# ---------- 1. 日報酬區塊重抽樣 ----------
def mc_bootstrap(report, n=5000, block=20, horizon=None, cagr_keep=1.0, rf=0.02, seed=0, show=True):
    """把回測的每日報酬切成連續區塊, 隨機抽回來重組成 n 條淨值曲線。

    block     : 每段連續抽幾天。20 約一個月, 保留連續虧損與波動群聚;
                設 1 等於逐日亂抽, 會低估連續虧損, 不建議
    horizon   : 每條路徑幾個交易日。None = 與回測同長; 252 = 看未來一年
    cagr_keep : 年化打幾折 (0.6 = 打六折), 做法是每天扣固定報酬, 波動不變
    回傳每條路徑的 cagr / mdd / sharpe
    """
    r = _daily_returns(report)
    T = len(r)
    if cagr_keep != 1:
        base_cagr = _stats(np.r_[1.0, np.cumprod(1 + r)][None, :], rf)['cagr'].iloc[0]
        r = r - _shift_for_cagr(r, base_cagr * cagr_keep)
    horizon = horizon or T
    block = max(1, min(block, T))
    n_blk = -(-horizon // block)
    rng = np.random.default_rng(seed)

    out = []
    for i in range(0, n, 1000):                       # 分批算, 避免 Colab 記憶體不夠
        m = min(1000, n - i)
        start = rng.integers(0, T - block + 1, size=(m, n_blk))
        idx = (start[:, :, None] + np.arange(block)).reshape(m, -1)[:, :horizon]
        eq = np.hstack([np.ones((m, 1)), np.cumprod(1 + r[idx], axis=1)])
        out.append(_stats(eq, rf))
    sims = pd.concat(out, ignore_index=True)

    if show:
        same = horizon == T and cagr_keep == 1
        base = _report_stats(report, rf) if same else None
        idx = report.creturn.dropna().index
        print(f"\n[區塊重抽樣] {n} 條路徑 | 每段 {block} 日 | 長度 {horizon} 日 (約 {horizon / DAYS:.1f} 年)"
              + (f" | 年化打 {cagr_keep:.0%}" if cagr_keep != 1 else ""))
        _show(_table(sims, base))
        msg = [f"年化 < 0 的機率 {(sims.cagr < 0).mean():.1%}"]
        if base is not None:
            msg.append(f"MDD 比原始 {base.mdd:.1%} 更深的機率 {(sims.mdd < base.mdd).mean():.1%}")
        msg += [f"MDD 超過 {x:.0%} 的機率 {(sims.mdd <= x).mean():.1%}" for x in (-0.3, -0.5)]
        print("  " + " | ".join(msg))
        print(f"  抽樣來源只有 {idx[0].date()} ~ {idx[-1].date()} 的報酬, 這段期間沒出現過的行情不會被模擬出來")
    return sims


# ---------- 2. 隨機剔除交易 ----------
def _spell_keep(held, drop, rng):
    """以「一段連續持有」為單位決定剔除與否, 同一筆交易不會被切碎而多出換手"""
    entry = held & ~np.vstack([np.zeros((1, held.shape[1]), bool), held[:-1]])
    spell = np.cumsum(entry, axis=0)
    keep = rng.random((spell.max() + 1, held.shape[1])) >= drop
    return held & np.take_along_axis(keep, spell, axis=0)


def mc_drop_trades(report, position, sim_kwargs, drop=0.2, n=30, seed=0, sim_fn=None, show=True):
    """隨機剔除 drop 比例的交易後重跑 sim, 模擬漏單、買不到漲停、資金不夠少買幾檔。
    布林持股: 剩下的股票由 sim 自動等權; 浮點權重: 剩下的部位等比例放大, 維持原本總曝險。
    剔除兩成績效就崩, 代表報酬集中在少數幾筆。每次重跑一次 sim, n=30 在 Colab 約需數分鐘。
    """
    sim_fn = sim_fn or _finlab_sim()
    kw = {**sim_kwargs, 'upload': False}
    is_bool = all(dt == bool for dt in position.dtypes)
    p = position.fillna(0).astype(float)
    w0 = p.to_numpy()
    held = w0 > 0
    total = w0.sum(axis=1)
    rng = np.random.default_rng(seed)

    rows = []
    for i in range(n):
        keep = _spell_keep(held, drop, rng)
        if is_bool:
            pos_i = pd.DataFrame(keep, index=p.index, columns=p.columns)
        else:
            w = np.where(keep, w0, 0.0)
            s = w.sum(axis=1)
            w *= np.divide(total, s, out=np.zeros_like(s), where=s > 0)[:, None]
            pos_i = pd.DataFrame(w, index=p.index, columns=p.columns)
        rows.append(_report_stats(sim_fn(pos_i, **kw)))
        print(f"\r  剔除交易 {i + 1}/{n}", end='')
    print()
    sims = pd.DataFrame(rows).reset_index(drop=True)

    if show:
        base = _report_stats(report)
        print(f"\n[隨機剔除 {drop:.0%} 交易] 重跑 {n} 次")
        _show(_table(sims, base))
        print(f"  年化中位數為原始的 {sims.cagr.median() / base.cagr:.0%} | "
              f"年化不到原始一半的比例 {(sims.cagr < base.cagr / 2).mean():.0%} | "
              f"年化 < 0 的比例 {(sims.cagr < 0).mean():.0%}")
    return sims


# ---------- 3. 隨機選股對照 ----------
def _groups(index, resample):
    """每一列對應到哪個換股期; 同一期內隨機持股不變, 不論 sim 實際在哪一天換股"""
    if isinstance(resample, str):
        try:
            return pd.factorize(index.to_period(resample))[0]
        except (ValueError, TypeError, AttributeError):
            pass
    return None


def mc_random_picks(report, position, universe, sim_kwargs, n=30, seed=0, sim_fn=None, show=True):
    """每個換股期從 universe 隨機挑「與原策略同檔數」的股票等權持有,
    並讓換手率跟原策略一樣 (原策略這期留下幾成舊股, 隨機組合也留下幾成)。

    universe: 布林表, 用原策略的流動性與基本門檻, 不含選股因子
              例如策略C 的 liq1, 或 condition3 & condition7
    結果回答: 原策略的報酬有多少來自選股, 多少只是「這段期間買流動性好的股票本來就會賺」。
    """
    sim_fn = sim_fn or _finlab_sim()
    kw = {**sim_kwargs, 'upload': False}
    p = position.fillna(0).astype(float)
    held = p.to_numpy() > 0
    u = (universe.astype(float).reindex(index=p.index, method='ffill')
         .reindex(columns=p.columns).fillna(0).to_numpy() > 0)

    g = _groups(p.index, kw.get('resample'))
    if g is None:                                     # 沒有 resample: 原策略持股一變就算新的一期
        g = np.cumsum(np.r_[True, (held[1:] != held[:-1]).any(axis=1)]) - 1
    last = pd.Series(np.arange(len(g))).groupby(g).last().to_numpy()
    H, U = held[last], u[last]                        # 每期最後一列 = 換股依據
    k = H.sum(axis=1)
    stay = np.r_[0.0, (H[1:] & H[:-1]).sum(axis=1) / np.maximum(H[:-1].sum(axis=1), 1)]
    rng = np.random.default_rng(seed)

    rows = []
    for i in range(n):
        picks = np.zeros_like(H)
        prev = np.zeros(H.shape[1], bool)
        for t in range(len(H)):
            old_pool = np.flatnonzero(prev & U[t])
            n_old = min(int(round(stay[t] * prev.sum())), k[t], len(old_pool))
            new_pool = np.flatnonzero(U[t] & ~prev)
            n_new = min(k[t] - n_old, len(new_pool))
            picks[t, rng.choice(old_pool, n_old, replace=False)] = True
            picks[t, rng.choice(new_pool, n_new, replace=False)] = True
            prev = picks[t]
        pos_i = pd.DataFrame(picks[g], index=p.index, columns=p.columns)
        rows.append(_report_stats(sim_fn(pos_i, **kw)))
        print(f"\r  隨機選股 {i + 1}/{n}", end='')
    print()
    sims = pd.DataFrame(rows).reset_index(drop=True)

    if show:
        base = _report_stats(report)
        print(f"\n[隨機選股對照] {n} 組, 每期檔數與換手率同原策略")
        _show(_table(sims, base))
        beat = int((sims.cagr >= base.cagr).sum())
        print(f"  隨機組合年化中位數 {sims.cagr.median():+.1%}, 原策略 {base.cagr:+.1%} | "
              f"隨機組合追上原策略: {beat}/{n} 次 (經驗 p 值約 {(beat + 1) / (n + 1):.2f})")
    return sims
