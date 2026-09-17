# 本地复现说明

## 一键复现（推荐）

```bash
cd reproduce
bash run_all.sh          # macOS / Linux
```

Windows（PowerShell 或 Git Bash）：

```powershell
cd reproduce
python study11_is.py     # 分步执行等效于 run_all.sh
python study11_oos.py
python study11_extra.py
python monte_carlo.py
cd ..
python build_html.py
```

约 5-10 分钟（多数时间在 1m K 线加载）。跑完后打开上一级的 `index.html` 查看报告。

## 环境要求

- Python 3.9+（在 3.10 验证）
- pandas、numpy：`pip install pandas numpy`
- 无需任何 API key、无需网络（Chart.js 走 CDN，仅打开报告页面时需要）
- `PYTHON` 环境变量可指定解释器：`PYTHON=python3.11 bash run_all.sh`

脚本会自动做三项检查并给出可操作的报错：python 是否存在、pandas/numpy 是否装好、数据目录是否完整。

## 分步运行

| 步骤 | 命令 | 输出 |
|---|---|---|
| 1. 资格审计 + IS 品种筛选（60d） | `python study11_is.py` | eligible_universe.csv · strategy_frozen_config.json |
| 2. OOS 评估（30d，只读冻结配置） | `python study11_oos.py` | oos_results.json · trade_log.csv |
| 3. 诊断（成本/LOO/synthetic/重采样） | `python study11_extra.py` | cost_sensitivity.csv 等 7 个 |
| 4. 蒙特卡洛 2000 次 | `python monte_carlo.py` | ../data/monte_carlo.json |
| 5. 重建 HTML 报告 | `python build_html.py`（在上级目录） | index.html |

## 文件说明

- `study11_core.py` — 数据加载 / 因果执行引擎（next_open / get_bar）/ funding 计价 / 指标。全部路径相对本目录（`os.path.dirname(__file__)`），无任何绝对路径
- `study11_is.py` — 60 天 IS：资格门槛 → 复合评分 → nested Dev/Val 选 K → 冻结配置
- `study11_oos.py` — 30 天 OOS：只读冻结配置 → 回测 → 三基准 → 衰减
- `study11_extra.py` — 成本曲线 / LOO / synthetic tick / 多周期诊断 / beta 回归
- `monte_carlo.py` — IID bootstrap / 块 bootstrap / 随机场 placebo（写入 ../data/）

## 复现性保证

- 全部随机过程固定种子（`np.random.default_rng(42)`）
- 已在干净目录（删除全部输出后）完整重跑验证：OOS 指标逐位一致（mean 75.2bp / 4/4 胜 / +3.04% / Sharpe 9.01），MC 分布一致（A p5=14.4bp、C 99.2 分位）
- 冻结配置 `strategy_frozen_config.json` 记录选中的 9 个资产与规则参数；OOS runner 只读

## 数据窗口

- IS：2026-06-19 → 2026-08-17（9 个周末）
- OOS：2026-08-18 → 2026-09-13（4 个周末，最后一个完整周末）
