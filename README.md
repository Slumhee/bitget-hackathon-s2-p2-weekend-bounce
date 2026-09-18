# P2 Weekend Bounce Harvester

> Bitget AI Base Camp Hackathon S2 · Track 1 Alpha Factory · 子主题：休市信息定价

回测展示页面(可复现): [github page](https://slumhee.github.io/bitget-hackathon-s2-p2-weekend-bounce/)

当美股闭市、定价权交给 crypto 交易者时，周六早盘的下跌是"无信息超调"。
本策略在周六正午买入早盘下跌的 Stock Perpetual、周日晚间平仓，收割超调回归。

**一句话：不是预测方向，是交易市场微观结构的时间性错位。**

## 成绩速览（60D IS + 30D OOS，净 12bp 成本）

| 指标 | IS (9 周末) | OOS (4 周末, untouched) |
|---|---|---|
| 周末净收益均值 | +27.7bp | +75.2bp |
| 胜率 | 66.7% | 100% (4/4) |
| Sharpe (年化) | 3.12 | 9.01 |
| MaxDD | -0.46% | 0% |
| 最差周末 | -40.5bp | +15.2bp |

- 复利总收益：OOS 30 天 +3.04%
- 蒙特卡洛 2000 次：bootstrap P(负)=0；随机场 placebo 中观测值位于 99.2 分位
- 成本压力 4→18bp RT 全档为正；break-even ≈ 87bp（现实成本的 7 倍）
- BTC beta 0.48，残差 alpha +57.7bp/周末——一半 crypto beta、一半纯股票永续 alpha

## 目录结构

```
p2-weekend-bounce/
├── index.html              ← 回测报告（GitHub Pages 入口，直接打开）
├── README.md               ← 本文件
├── build_html.py           ← 报告生成脚本
├── report_template.html    ← 报告模板
├── data/                   ← 全部结果数据（CSV/JSON）
│   ├── strategy_frozen_config.json   冻结策略配置
│   ├── trade_log.csv                 37 笔交易明细
│   ├── weekend_returns.csv           周末组合收益（统计单位）
│   ├── portfolio_equity.csv          资金曲线
│   ├── monte_carlo.json              2000 次蒙特卡洛
│   └── ...                           成本/LOO/beta/诊断
├── reproduce/              ← 本地复现入口（见 reproduce/README.md）
│   ├── run_all.sh          一键复现全部结果
│   ├── study11_*.py        核心管线（数据→筛选→IS→OOS→诊断）
│   ├── monte_carlo.py      蒙特卡洛
│   ├── pair_1m/            原始 1m K 线（306MB, 22 资产）
│   └── pair_funding/       真实 funding 历史
└── tech/                   ← 技术层（第二层）
    ├── TECHNICAL.md        架构图 + 策略逻辑图 + 数据流
    ├── COST_STRESS.md      成本压力与执行假设报告
    └── LOO_ROBUSTNESS.md   Leave-One-Out 稳健性报告
```

## 快速复现

```bash
cd reproduce
bash run_all.sh        # 约 5-10 分钟，即可重新生成全部结果
```

依赖：Python 3.10+，pandas，numpy。无需 API key（原始数据已随包附带）。

## 策略规则（冻结 v1.0）

1. **Universe**：9 个 Stock Perpetual（IS 内选出）：SPY META NFLX AAPL HOOD COIN TSLA QQQ RDDT
2. **入场**：周六 00:00→12:00 UTC 收盘收益 < 0 → 12:01 bar open 市价买入
3. **权重**：篮内等权 1/N，组合总敞口 1x
4. **出场**：周日 21:00 bar → 21:01 open 全平；同周末不再入场
5. **成本**：taker 12bp RT；funding 按真实历史事件逐笔计入

## 合规声明

- 交易腿 100% Bitget Stock Perpetual；BTC 仅作对照/回归，不进组合
- 信号→执行严格 next-bar，无同 bar 泄漏；无未来函数
- 品种选择、K 值、全部参数在 60D IS 内冻结；30D OOS 只读配置
- 统计单位 = 周末组合收益（同周末资产高度相关，不虚增样本）
