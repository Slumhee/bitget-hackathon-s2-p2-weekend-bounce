"""Nautilus strategy: P2 Weekend Bounce Harvester (frozen v1.0, 1h bars).

Faithful 1h-bar expression of the frozen rules:
  - signal ref A: Saturday 00:00 UTC bar close   (bar open 23:00 Fri)
  - signal ref B: Saturday 12:00 UTC bar close   (bar open 11:00 Sat)
  - entry:  if B < A  -> market buy at the open of the next bar (12:00 Sat bar
    open == 12:00 UTC price, executed on bar OPEN of the 12:00-13:00 bar)
  - exit:   close all at the open of the Sunday 21:00 UTC bar (20:00 bar open
    follows the 20:00 close == 21:00 price)

State machine keyed on UTC weekday/hour of each 1h bar. Equal-weight 1/N
sizing across the frozen 9-symbol universe; gross exposure = number of
triggered names × 1/9 × budget.
"""
from decimal import Decimal
from typing import Optional

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

SIGNAL_HOUR = 12  # Sat 12:00 UTC close is the signal reference B
EXIT_HOUR = 21    # Sun 21:00 UTC (open of the 21:00 bar) flatten


def _utc_parts(ts_ns) -> tuple:
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
    return dt.weekday(), dt.hour, dt.date()


class P2WeekendBounceConfig(StrategyConfig):
    instrument_ids: tuple[InstrumentId, ...] = ()
    bar_types: tuple[BarType, ...] = ()
    budget: str = "100000"
    n_universe: int = 9
    max_positions: int = 9


class P2WeekendBounceStrategy(Strategy):
    def __init__(self, config: P2WeekendBounceConfig) -> None:
        super().__init__(config)
        self.cfg = config
        self._sat_ref_close: dict[InstrumentId, float] = {}   # Sat 00:00 closes
        self._pending: dict[InstrumentId, float] = {}          # ref A candidates this week
        self._ref_a: dict[InstrumentId, float] = {}            # confirmed Sat 00:00 close
        self._ref_b: dict[InstrumentId, float] = {}            # Sat 12:00 close
        self._entered_week: Optional[object] = None            # date key of current weekend
        self._instruments: dict[InstrumentId, Instrument] = {}

    def on_start(self) -> None:
        for bt in self.cfg.bar_types:
            self.subscribe_bars(bt)
        for iid in self.cfg.instrument_ids:
            self._instruments[iid] = self.cache.instrument(iid)

    # ------------------------------------------------------------------ core
    def on_bar(self, bar: Bar) -> None:
        iid = bar.bar_type.instrument_id
        wd, hr, d = _utc_parts(bar.ts_event)
        close = float(bar.close)

        # Sat 00:00 close lands on the bar with open Fri 23:00 (hr==23, wd==4)
        if wd == 4 and hr == 23:
            self._ref_a[iid] = close
            self._entered_week = d
            return
        # Sat 12:00 close lands on the bar with open 11:00 (wd==5, hr==11)
        if wd == 5 and hr == 11:
            self._ref_b[iid] = close
            self._maybe_enter(iid, close)
            return
        # Sun 21:00 flatten: bar open 21:00 (wd==6, hr==21)
        if wd == 6 and hr == 21:
            self._flatten(iid)
            return

    def _maybe_enter(self, iid: InstrumentId, ref_px: float) -> None:
        if iid not in self._instruments or self._ref_a.get(iid) is None:
            return
        if self._positions_open_count() >= self.cfg.max_positions:
            return
        a, b = self._ref_a[iid], self._ref_b[iid]
        if b is None or a is None or b / a - 1 >= 0:
            return
        inst = self._instruments[iid]
        per_name = Decimal(self.cfg.budget) / Decimal(self.cfg.n_universe)
        qty = self._qty_for_notional(inst, per_name, ref_px)
        if qty is None or qty <= 0:
            return
        order = self.order_factory.market(
            instrument_id=iid,
            order_side=OrderSide.BUY,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)

    def _flatten(self, iid: InstrumentId) -> None:
        for pos in self.cache.positions_open(instrument_id=iid):
            qty = pos.quantity
            order = self.order_factory.market(
                instrument_id=iid,
                order_side=OrderSide.SELL if pos.side.name == "LONG" else OrderSide.BUY,
                quantity=qty,
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)
        # reset weekly refs
        self._ref_a.pop(iid, None)
        self._ref_b.pop(iid, None)

    def _positions_open_count(self) -> int:
        return sum(len(self.cache.positions_open(instrument_id=iid))
                   for iid in self._instruments)

    def _qty_for_notional(self, inst: Instrument, notional: Decimal, ref_px: float) -> Optional[Quantity]:
        if not ref_px or ref_px <= 0:
            return None
        raw = notional / Decimal(str(ref_px))
        return Quantity(raw.quantize(Decimal(1).scaleb(-inst.size_precision)), inst.size_precision)

    def on_stop(self) -> None:
        for iid in self._instruments:
            self.cancel_all_orders(iid)
            self.close_all_positions(iid)
