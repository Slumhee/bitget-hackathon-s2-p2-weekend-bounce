"""Entry point for the P2 Weekend Bounce Harvester Playbook.

Historical mode: fetch Bitget US-stock-perp 1h bars via getagent.data, replay
the frozen weekend rules through the Nautilus engine, and emit a summary
signal with the sandbox backtest metrics.

Live mode: every scheduled run (Sat 12:00 UTC) measures the weekend morning
return per symbol from live 1h bars and emits the basket decision; execution
flows through the managed follow-trade callback.
"""
import math
from decimal import Decimal
from typing import Any

from getagent import backtest, data, runtime

SYMBOLS = [
    "SPYUSDT", "METAUSDT", "NFLXUSDT", "AAPLUSDT", "HOODUSDT",
    "COINUSDT", "TSLAUSDT", "QQQUSDT", "RDDTUSDT",
]
INTERVAL = "1h"
VENUE = "BITGET"


def _sanitize(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _fetch_1h(symbol: str, days: int = 90) -> list[dict]:
    """Fetch closed 1h bars for one symbol, paginating past the 1000-bar cap.

    The platform caps each response at 1000 bars and truncates silently from
    the window end, so we page backward with end_time until the requested
    day-count is covered or the feed runs dry. De-dup by bar open time.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    all_rows: dict = {}
    end_time = int(now.timestamp() * 1000)  # endpoint rejects None
    floor = int((now - timedelta(days=days)).timestamp() * 1000)
    for _page in range(6):  # 90d of 1h bars needs ~3 pages; cap at 6
        bars = data.crypto.futures.kline(
            symbol=symbol,
            interval=INTERVAL,
            exchange="bitget",
            limit=1000,
            end_time=end_time,
            closed_only=True,
        )
        rows = data.to_records(bars)
        if not rows:
            break
        for row in rows:
            ts = row.get("time") or row.get("date")
            if ts is None:
                continue
            key = int(ts) if str(ts).isdigit() else ts
            all_rows[key] = row
        oldest = None
        for row in rows:
            ts = row.get("time") or row.get("date")
            if ts is None:
                continue
            v = int(ts) if str(ts).isdigit() else None
            if v is not None and (oldest is None or v < oldest):
                oldest = v
        if oldest is None or oldest <= floor:
            break
        end_time = oldest - 1
    return [all_rows[k] for k in sorted(all_rows, key=lambda x: str(x))]


def _run_historical() -> None:
    frames = {}
    total_rows = 0
    for sym in SYMBOLS:
        rows = _fetch_1h(sym)
        if not rows:
            continue
        frame = backtest.prepare_frame(rows, datetime_index="date")
        frames[f"{sym}.{VENUE}"] = frame
        total_rows += len(frame)

    if not frames:
        runtime.emit_signal(
            action="watch", symbol=SYMBOLS[0], confidence=0.0,
            metrics={"rows": 0},
            meta={"reason": "no historical bars returned"},
        )
        return

    result = backtest.run(ohlcv_data=frames, spec=runtime.backtest_spec)
    chart_path = backtest.generate_chart(result)
    summary = result.summary or {}
    try:
        net_pnl = float(summary.get("net_pnl", 0) or 0)
    except (TypeError, ValueError):
        net_pnl = 0.0
    last_ts = 0
    for frame in frames.values():
        try:
            last_ts = max(last_ts, int(frame.index.max().timestamp() * 1000))
        except Exception:  # noqa: BLE001
            pass

    runtime.emit_signal(
        action="long" if net_pnl > 0 else "watch",
        symbol=SYMBOLS[0],
        confidence=_sanitize(result.win_rate) or 0.0,
        metrics={
            "total_return_pct": _sanitize(result.total_return_pct),
            "net_pnl": net_pnl,
            "starting_balance": summary.get("starting_balance"),
            "sharpe_ratio": _sanitize(result.sharpe_ratio),
            "max_drawdown_pct": _sanitize(result.max_drawdown_pct),
            "win_rate": _sanitize(result.win_rate),
            "total_trades": _sanitize(result.total_trades),
            "profit_factor": _sanitize(result.profit_factor),
            "rows": total_rows,
            "last_bar_ts": last_ts,
        },
        meta={"chart_path": chart_path, "symbols": SYMBOLS,
              "strategy": "P2 weekend bounce, frozen v1.0 (Sat 12:00 entry, Sun 21:00 exit)"},
    )


def _weekend_morning_return(sym: str) -> Decimal | None:
    """Live: Sat 00:00 UTC close -> Sat 12:00 UTC close from closed 1h bars."""
    rows = _fetch_1h(sym)
    if not rows:
        return None
    ref_a = None
    ref_b = None
    from datetime import datetime, timezone
    for row in rows:
        # SDK returns `time` (ms epoch) and/or `date` (ISO string) depending on source
        ts = row.get("time")
        if ts is not None:
            try:
                dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
            except (TypeError, ValueError):
                continue
        else:
            ds = row.get("date")
            if not ds:
                continue
            try:
                dt = datetime.fromisoformat(str(ds).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        # Sat 00:00 close == bar opened Fri 23:00 (last bar before Sat 00:00)
        if dt.weekday() == 4 and dt.hour == 23:
            ref_a = Decimal(str(row["close"]))
        # Sat 12:00 close == bar opened 11:00
        if dt.weekday() == 5 and dt.hour == 11:
            ref_b = Decimal(str(row["close"]))
    if ref_a is None or ref_b is None:
        return None
    return (ref_b / ref_a - 1) * Decimal(10000)  # bp


def _execute_contract_signal(*, symbol: str, margin_budget: str, leverage: int) -> dict:
    from getagent import trade

    current = trade.contract.current_position(symbol=symbol)
    position = trade.helpers.find_contract_position(current, symbol=symbol)
    if position is not None and position.hold_side == "long":
        return {"status": "already_positioned", "hold_side": position.hold_side}

    qty_plan = trade.helpers.compute_qty(
        symbol=symbol, market="contract",
        budget_amount=margin_budget, leverage=leverage,
    )
    result = trade.contract.open_long_market(symbol=symbol, qty=qty_plan.qty, leverage=leverage)
    if not trade.is_success(result):
        raise RuntimeError(f"contract open failed: {result}")
    return {"qty": str(qty_plan.qty), "result": result}


def _run_live() -> None:
    cfg = runtime.manifest.get("strategy_config", {}) or {}
    budget = str(cfg.get("total_budget", "100000"))
    n = int(cfg.get("per_symbol_fraction_num", 9))
    max_positions = int(cfg.get("max_positions", 9))
    per_name = str(Decimal(budget) / Decimal(n))
    leverage = 1

    selected = []
    returns = {}
    for sym in SYMBOLS:
        ret_bp = _weekend_morning_return(sym)
        if ret_bp is None:
            continue
        returns[sym] = float(ret_bp)
        if ret_bp < 0:
            selected.append(sym)

    selected = selected[:max_positions]
    action = "long" if selected else "hold"
    runtime.emit_signal_or_follow(
        action=action,
        symbol=selected[0] if selected else SYMBOLS[0],
        confidence=0.75 if selected else 0.0,
        metrics={
            "selected": selected,
            "morning_returns_bp": returns,
            "per_name_notional": per_name,
            "leverage": leverage,
        },
        meta={"weekend_rule": "Sat 00:00->12:00 UTC close return < 0 -> long; Sun 21:00 UTC flatten",
              "universe": SYMBOLS},
        execute_trade=(
            lambda sym=selected[0]: _execute_contract_signal(
                symbol=sym, margin_budget=per_name, leverage=leverage)
        ) if selected else None,
    )


def run() -> None:
    if runtime.is_historical():
        _run_historical()
        return
    if runtime.is_live():
        _run_live()
        return
    raise ValueError(f"unsupported evaluation_mode={runtime.evaluation_mode!r}")


if __name__ == "__main__":
    run()
