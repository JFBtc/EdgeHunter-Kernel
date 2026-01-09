"""
Engine Loop - Single-writer kernel loop
Publishes atomic snapshots at fixed frequency (10 Hz default)
"""
import math
import time
import threading
import uuid
from typing import Optional

from src.clock import ClockProtocol, SessionManager, SystemClock
from src.command_queue import CommandQueue
from src.event_queue import InboundQueue
from src.events import AdapterErrorEvent, QuoteEvent, StatusEvent
from src.gates import GateInputs, evaluate_hard_gates
from src.snapshot import (
    ControlsDTO,
    FeedDTO,
    GatesDTO,
    InstrumentDTO,
    LoopHealthDTO,
    QuoteDTO,
    SessionDTO,
    SnapshotDTO,
)
from src.datahub import DataHub


class EngineLoop:
    """
    Single-writer engine loop that publishes atomic snapshots.

    V1a.1 Slice 1: Minimal loop without feed, gates, or commands.
    Just publishes snapshots with monotonic IDs at fixed frequency.
    """

    def __init__(
        self,
        datahub: DataHub,
        cycle_target_ms: int = 100,  # 10 Hz
        overrun_threshold_ms: int = 500,
        inbound_queue: Optional[InboundQueue] = None,
        command_queue: Optional[CommandQueue] = None,
        clock: Optional[ClockProtocol] = None,
    ):
        self.datahub = datahub
        self.cycle_target_ms = cycle_target_ms
        self.overrun_threshold_ms = overrun_threshold_ms
        self.inbound_queue = inbound_queue
        self.command_queue = command_queue
        self.clock = clock or SystemClock()
        self.session_mgr = SessionManager(clock=self.clock)

        # Run identity
        self.run_id = str(uuid.uuid4())
        self._run_start_ts_unix_ms = self.clock.now_unix_ms()

        # State
        self._snapshot_id = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Controls (placeholders for Slice 1)
        self._intent = "FLAT"
        self._arm = False
        self._last_cmd_id = 0
        self._last_cmd_ts_unix_ms: Optional[int] = None

        # Feed + quote state (J2/J3)
        self._feed_connected = False
        self._md_mode = "NONE"
        self._feed_status_reason_codes: list[str] = []
        self._feed_last_status_change_mono_ns: Optional[int] = None

        self._quote_bid: Optional[float] = None
        self._quote_ask: Optional[float] = None
        self._quote_last: Optional[float] = None
        self._quote_bid_size: Optional[int] = None
        self._quote_ask_size: Optional[int] = None
        self._quote_ts_recv_unix_ms: Optional[int] = None
        self._quote_ts_recv_mono_ns: Optional[int] = None
        self._quote_ts_exch_unix_ms: Optional[int] = None

        self._last_any_event_mono_ns: Optional[int] = None
        self._last_quote_event_mono_ns: Optional[int] = None
        self._quotes_received_count = 0

    def start(self) -> None:
        """Start the engine loop in a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the engine loop gracefully."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run_loop(self) -> None:
        """
        Main engine loop: publish snapshot at fixed frequency.

        V1a.1 Slice 1: No events, no commands, no gates yet.
        Just publishes snapshots with monotonic IDs and loop health.
        """
        while self._running:
            cycle_elapsed_ms = self._run_cycle_once()

            # Sleep to maintain target frequency
            sleep_ms = max(0, self.cycle_target_ms - cycle_elapsed_ms)
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)

    def _run_cycle_once(self) -> int:
        cycle_start_mono_ns = self.clock.now_mono_ns()
        cycle_start_unix_ms = self.clock.now_unix_ms()

        # Increment snapshot ID (monotonic)
        self._snapshot_id += 1

        # CYCLE BOUNDARY: Drain and apply commands (last-write-wins coalescing)
        self._drain_commands()

        # Drain inbound events for liveness/feed/quote
        self._drain_inbound_events()

        session_date_iso = self.session_mgr.session_date_iso()
        in_operating = self.session_mgr.in_operating_window()
        is_break = self.session_mgr.is_break_window()
        session_phase = self.session_mgr.session_phase()

        quote_staleness_ms = None
        if self._quote_ts_recv_mono_ns is not None:
            quote_staleness_ms = max(
                0, (cycle_start_mono_ns - self._quote_ts_recv_mono_ns) // 1_000_000
            )

        spread_ticks = None
        if (
            self._quote_bid is not None
            and self._quote_ask is not None
            and self._quote_ask > self._quote_bid
        ):
            tick_size = InstrumentDTO().tick_size
            spread_ticks = int(math.ceil((self._quote_ask - self._quote_bid) / tick_size))

        feed_degraded = (not self._feed_connected) or (self._md_mode != "REALTIME")
        feed_reasons = []
        if not self._feed_connected:
            feed_reasons.append("FEED_DISCONNECTED")
        if self._md_mode != "REALTIME":
            feed_reasons.append("MD_NOT_REALTIME")

        # Compute cycle time before gates (gates need engine_degraded input)
        pre_gate_elapsed_ms = int(
            (self.clock.now_mono_ns() - cycle_start_mono_ns) / 1_000_000
        )
        engine_degraded = pre_gate_elapsed_ms > self.overrun_threshold_ms

        gate_inputs = GateInputs(
            arm=self._arm,
            intent=self._intent,
            in_operating_window=in_operating,
            is_break_window=is_break,
            feed_connected=self._feed_connected,
            md_mode=self._md_mode,
            con_id=InstrumentDTO().con_id,
            bid=self._quote_bid,
            ask=self._quote_ask,
            last=self._quote_last,
            quote_staleness_ms=quote_staleness_ms,
            last_quote_event_mono_ns=self._last_quote_event_mono_ns,
            ts_mono_ns=cycle_start_mono_ns,
            spread_ticks=spread_ticks,
            engine_degraded=engine_degraded,
        )
        allowed, reasons, gate_metrics = evaluate_hard_gates(gate_inputs)

        # Final cycle time after gates
        cycle_elapsed_ms = int(
            (self.clock.now_mono_ns() - cycle_start_mono_ns) / 1_000_000
        )
        cycle_overrun = cycle_elapsed_ms > self.cycle_target_ms

        snapshot = SnapshotDTO(
            schema_version="snapshot.v1",
            run_id=self.run_id,
            run_start_ts_unix_ms=self._run_start_ts_unix_ms,
            snapshot_id=self._snapshot_id,
            cycle_count=self._snapshot_id,
            ts_unix_ms=cycle_start_unix_ms,
            ts_mono_ns=cycle_start_mono_ns,
            instrument=InstrumentDTO(),
            feed=FeedDTO(
                connected=self._feed_connected,
                md_mode=self._md_mode,
                degraded=feed_degraded,
                status_reason_codes=feed_reasons or self._feed_status_reason_codes,
                last_status_change_mono_ns=self._feed_last_status_change_mono_ns,
            ),
            quote=QuoteDTO(
                bid=self._quote_bid,
                ask=self._quote_ask,
                last=self._quote_last,
                bid_size=self._quote_bid_size,
                ask_size=self._quote_ask_size,
                ts_recv_unix_ms=self._quote_ts_recv_unix_ms,
                ts_recv_mono_ns=self._quote_ts_recv_mono_ns,
                ts_exch_unix_ms=self._quote_ts_exch_unix_ms,
                staleness_ms=quote_staleness_ms,
                spread_ticks=spread_ticks,
            ),
            session=SessionDTO(
                in_operating_window=in_operating,
                is_break_window=is_break,
                session_date_iso=session_date_iso,
                session_phase=session_phase,
            ),
            controls=ControlsDTO(
                intent=self._intent,
                arm=self._arm,
                last_cmd_id=self._last_cmd_id,
                last_cmd_ts_unix_ms=self._last_cmd_ts_unix_ms,
            ),
            loop=LoopHealthDTO(
                cycle_ms=cycle_elapsed_ms,
                cycle_overrun=cycle_overrun,
                engine_degraded=engine_degraded,
                last_cycle_start_mono_ns=cycle_start_mono_ns,
            ),
            gates=GatesDTO(
                allowed=allowed,
                reason_codes=reasons,
                gate_metrics=gate_metrics,
            ),
            last_any_event_mono_ns=self._last_any_event_mono_ns,
            last_quote_event_mono_ns=self._last_quote_event_mono_ns,
            quotes_received_count=self._quotes_received_count,
            ready=allowed,
            ready_reasons=reasons,
        )

        self.datahub.publish(snapshot)
        return cycle_elapsed_ms

    def _drain_inbound_events(self) -> None:
        if not self.inbound_queue:
            return

        for event in self.inbound_queue.drain():
            self._last_any_event_mono_ns = event.ts_recv_mono_ns

            if isinstance(event, QuoteEvent):
                self._last_quote_event_mono_ns = event.ts_recv_mono_ns
                self._quotes_received_count += 1
                if event.bid is not None:
                    self._quote_bid = event.bid
                if event.ask is not None:
                    self._quote_ask = event.ask
                if event.last is not None:
                    self._quote_last = event.last
                if event.bid_size is not None:
                    self._quote_bid_size = event.bid_size
                if event.ask_size is not None:
                    self._quote_ask_size = event.ask_size
                self._quote_ts_recv_unix_ms = event.ts_recv_unix_ms
                self._quote_ts_recv_mono_ns = event.ts_recv_mono_ns
                self._quote_ts_exch_unix_ms = event.ts_exch_unix_ms
            elif isinstance(event, StatusEvent):
                prev_connected = self._feed_connected
                prev_md_mode = self._md_mode
                self._feed_connected = bool(event.connected)
                self._md_mode = (
                    event.md_mode.value
                    if hasattr(event.md_mode, "value")
                    else str(event.md_mode)
                )
                if event.reason:
                    self._feed_status_reason_codes = [event.reason]
                if (self._feed_connected != prev_connected) or (self._md_mode != prev_md_mode):
                    self._feed_last_status_change_mono_ns = event.ts_recv_mono_ns
            elif isinstance(event, AdapterErrorEvent):
                if event.error_msg:
                    self._feed_status_reason_codes = [event.error_msg]

    def _drain_commands(self) -> None:
        """
        Drain CommandQueue at cycle boundary with last-write-wins coalescing.

        V1a-J3: Commands are the ONLY way UI can update Intent/ARM.
        Coalescing ensures deterministic application per cycle.
        """
        if not self.command_queue:
            return

        batch = self.command_queue.drain()

        # Apply coalesced Intent/ARM (last-write-wins)
        if batch.intent is not None:
            self._intent = batch.intent
        if batch.arm is not None:
            self._arm = batch.arm

        # Update command tracking (last command identity)
        if batch.last_cmd_id > 0:
            self._last_cmd_id = batch.last_cmd_id
            self._last_cmd_ts_unix_ms = batch.last_cmd_ts_unix_ms
