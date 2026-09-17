# TECHNICAL — 架构与策略逻辑

## 1 · System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA LAYER (offline)                          │
│  Bitget v2 API ──► pair_1m/*.jsonl      22 stock perps · 1m OHLCV   │
│                   pair_funding/*.jsonl  真实 funding 事件 (8h 周期)   │
│                   btc_1m.jsonl          BTC 对照组 (仅分析用)         │
└──────────────┬──────────────────────────────────────────────────────┘
               │ load1m()  去重/排序/类型化 (study11_core.py)
               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     ELIGIBILITY GATE (Data Audit)                    │
│  ≥90 天连续历史 + <2% missing + 覆盖 60D IS + 30D OOS 全窗            │
│  22 候选 ──► 14 eligible (MSFT/ORCL/ARM/BABA/AMZN/ASML/GME/MCD 出局) │
└──────────────┬──────────────────────────────────────────────────────┘
               ▼
┌───────────────────────────────────┐   ┌──────────────────────────────┐
│   IS ENGINE (06-19 → 08-17, 60d)  │   │  OOS RUNNER (08-18 → 09-13)   │
│  study11_is.py                    │   │  study11_oos.py               │
│  ┌─────────────────────────────┐  │   │  ┌──────────────────────────┐ │
│  │ per-symbol scoring          │  │   │  │ READ strategy_frozen_    │ │
│  │  consistency/risk/liquidity │  │   │  │ config.json (只读)        │ │
│  ├─────────────────────────────┤  │   │  ├──────────────────────────┤ │
│  │ nested Dev(40d)/Val(19d)    │  │   │  │ 同一 weekend_trades() 引擎│ │
│  │ K=6..12 扫描 → K=9          │──┼──►│  │ 零调参 · 零选择           │ │
│  ├─────────────────────────────┤  │   │  ├──────────────────────────┤ │
│  │ freeze → JSON config        │  │   │  │ benchmarks A/B/C          │ │
│  └─────────────────────────────┘  │   │  │ decay / beta / LOO        │ │
└───────────────────────────────────┘   └──────────────┬───────────────┘
               ▼                                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│          DIAGNOSTICS (study11_extra.py + monte_carlo.py)             │
│  cost curve · LOO asset/weekend · synthetic tick stress ·            │
│  multi-timeframe resampling · Monte Carlo ×2000 · BTC beta          │
└──────────────┬──────────────────────────────────────────────────────┘
               ▼
     data/*.csv ──► build_html.py ──► index.html (GitHub Pages)
```

## 2 · Strategy Logic Diagram

```
                      ┌──────────────────────────────┐
                      │  每周六 00:00 UTC（美股已闭市） │
                      └──────────────┬───────────────┘
                                     ▼
        ┌────────────────────────────────────────────────┐
        │ 对 9 个 universe 资产逐个计算                    │
        │   R_i = P_i(12:00)/P_i(00:00) − 1             │
        │   （两根已收盘 1m bar 的 close，无未来信息）      │
        └───────────────────┬────────────────────────────┘
                            ▼
              ┌──────────────────────────┐
              │  R_i < 0 ？              │
              └─────┬──────────────┬─────┘
                    │ yes          │ no
                    ▼              ▼
             入候选篮 L_i        不交易
                    │
                    ▼
        ┌────────────────────────────────────────┐
        │ 12:01 bar OPEN 市价买入（next-bar 因果） │
        │   w_i = 1/|candidates| · Σ|w| = 1x     │
        └───────────────────┬────────────────────┘
                            ▼
              ┌──────────────────────────┐
              │ 持仓 ~33h · 逐 funding    │
              │ 事件计费 · 5m MTM         │
              └─────────────┬────────────┘
                            ▼
        ┌────────────────────────────────────────┐
        │ 周日 21:00 bar 完成 → 21:01 OPEN 全平   │
        │ 同周末禁止再入场 · 周中零敞口            │
        └────────────────────────────────────────┘

  机制（为什么赚钱）:
    美股闭市 ──► crypto 交易者主导定价 ──► 周六早盘下跌=无信息超调
    ──► 无新基本面信息流 ──► 周日美股重定价前回补
    + 周末 crypto 反弹 beta（可对冲分离，beta=0.48）
```

## 3 · Execution & Causality 模型

| 环节 | 实现 | 防泄漏机制 |
|---|---|---|
| 信号 | Sat 00:00 / 12:00 两根已收 bar 的 close | 只用已完成 bar |
| 入场 | 12:00 bar 后第一根 bar 的 OPEN（`next_open()`） | 严格 timestamp > signal bar |
| 出场 | 21:00 bar 后第一根 bar 的 OPEN | 同上 |
| 滑点 | taker 全吃（12bp RT 含费）+ synthetic tick stress 至 100% 最差 intrabar | 不假设 maker 成交 |
| Funding | `funding_over(u, entry, exit)` 逐事件求和，多头付正费率 | 真实历史事件表 |
| 新资产/缺数据 | freshness 检查：参考 bar 距信号时刻 >6h 则跳过 | 防 stale 价格伪信号 |

## 4 · Multi-Timeframe Resampling（诊断用）

1m → 1h RV、1m → 4h Kaufman efficiency 均为**只向上重采样、bar 完全闭合后使用**（任务合规）。结论：与周末净收益无显著关系 → 不引入信号过滤，保持策略简单（详见 data/resampling_diagnostics.csv）。

## 5 · 数据完整性

- 22 个 Stock Perp 1m K 线共 ~306MB，Bitget v2 `mix/market/history-candles`（分页 endTime 回翻，limit 200/页）
- 文件为降序存储；loader 做去重+升序化
- 窗口：IS 2026-06-19→08-17（9 周末）· OOS 08-18→09-13（4 周末，最后完整周末）
- Funding：v2 `mix/market/history-fund-rate`，13 资产 ×270 事件
