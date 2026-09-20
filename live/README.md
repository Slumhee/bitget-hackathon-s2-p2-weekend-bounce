# Live 层 — Bitget 生态实时接入

在 main 分支 60D IS + 30D OOS 冻结回测之上，本目录把策略接入 Bitget 实时生态，
形成「回测 → 实时信号 → 模拟盘执行」的完整证据链。

## 组件

| 文件 | 作用 |
|---|---|
| `bitget_market.py` | Bitget 公共行情客户端（无 API key）。v2 mix `history-candles` 1m K 线，向后分页 + 磁盘增量缓存（`cache/`），限速 0.15s/页、429 退避重试 |
| `weekend_signal.py` | 实时信号引擎，与 `reproduce/study11_core.py` 因果逻辑严格一致：周六 00:00→12:00 UTC 收盘收益 <0 → 12:01 bar open 入场；周日 21:00 → 21:01 平仓。6h 新鲜度门槛与回测相同 |
| `paper_trader.py` | 周末交易循环（默认 5 分钟一轮）。shadow 模式按 next-bar open 模拟成交；设置 `BITGET_DEMO_API_KEY/SECRET/PASSPHRASE` 后自动切 demo 模式，经 `x-simulated-trading: 1` header 在 Bitget 模拟盘真实下单（UTA v2 HMAC 签名）。全部事件追加 JSONL 日志（`logs/paper_<saturday>.jsonl`）——即比赛要求的 paper-trading 证据材料 |

## 运行

```bash
# 拉取/增量刷新行情（公共端点，无需任何 key）
python3 live/bitget_market.py

# 查看本周末交易计划
python3 live/weekend_signal.py            # 或指定周六: python3 live/weekend_signal.py 2026-09-26

# 挂 paper trader（shadow 模式，ctrl-c 或跑完周末自动退出）
python3 live/paper_trader.py

# demo 模式（Bitget 模拟盘真实下单）
BITGET_DEMO_API_KEY=... BITGET_DEMO_SECRET=... BITGET_DEMO_PASSPHRASE=... \
PAPER_NOTIONAL=1000 python3 live/paper_trader.py
```

环境变量：`POLL_SECONDS`（默认 300）、`PAPER_NOTIONAL`（总名义 1x，默认 1000 USDT，篮内每标的 1/9）。

## 2026-09-19/20 周末实录（首个 live 周末）

- 信号（真实公共行情）：NFLX -16.6bp / HOOD -0.8bp / QQQ -19.2bp / RDDT -2.0bp → 4/9 入场
- 入场事件于周日补记（`entry_ts` 为因果信号 bar 时间，`logged_at` 如实记录补记时刻）；
  盯市与平仓自挂起后全程实时记录
- 日志：`logs/paper_2026-09-19.jsonl`

## 与回测的一致性

- 信号判定、next-bar 执行、新鲜度门槛：与冻结 v1.0 回测逐条对应
- 成本：shadow 模式按冻结假设 12bp RT 计入 `net_bp_shadow`；demo 模式为交易所真实模拟成交
- Universe：只读 `data/strategy_frozen_config.json` 的冻结 9 标的，不做任何在线重选
