"""
Tests for V1a J2 - Time + Liveness + Session Windows

Validates:
- Clock/Time utility with timezone support
- Session date computation (rolls at 17:00 local)
- Operating window and break window detection
- Liveness tracking fields
- Deterministic clock injection for testing
"""
import pytest
from datetime import datetime, timedelta, timezone

from src.clock import (
    SystemClock,
    SessionManager,
    ClockProtocol,
)
from src.snapshot import (
    SnapshotDTO,
    InstrumentDTO,
    FeedDTO,
    QuoteDTO,
    SessionDTO,
    ControlsDTO,
    LoopHealthDTO,
    GatesDTO,
)


class FrozenClock:
    """
    Deterministic clock for testing.

    Allows injecting specific times for reproducible tests.
    Uses naive datetime (no timezone dependency).
    """

    def __init__(
        self,
        frozen_dt: datetime,
        frozen_mono_ns: int = 1000000000,  # 1 second
    ):
        """
        Initialize frozen clock.

        Args:
            frozen_dt: Fixed datetime (timezone-aware or naive)
            frozen_mono_ns: Fixed monotonic time in nanoseconds
        """
        self.frozen_dt = frozen_dt
        self.frozen_mono_ns = frozen_mono_ns

    def now_unix_ms(self) -> int:
        """Wall-clock time in milliseconds since epoch (UTC)."""
        return int(self.frozen_dt.timestamp() * 1000)

    def now_mono_ns(self) -> int:
        """Monotonic time in nanoseconds."""
        return self.frozen_mono_ns

    def now_local(self) -> datetime:
        """Current time (returns frozen_dt as-is)."""
        return self.frozen_dt

    def now_utc(self) -> datetime:
        """Current time in UTC timezone."""
        if self.frozen_dt.tzinfo is None:
            # Naive datetime - assume UTC
            return self.frozen_dt.replace(tzinfo=timezone.utc)
        return self.frozen_dt.astimezone(timezone.utc)


# Test fixtures for common times (naive datetime - no tz dependency)
def test_system_clock_basic():
    """Test SystemClock provides real time."""
    clock = SystemClock()

    unix_ms = clock.now_unix_ms()
    mono_ns = clock.now_mono_ns()
    local_dt = clock.now_local()
    utc_dt = clock.now_utc()

    # Sanity checks
    assert unix_ms > 1700000000000  # After 2023
    assert mono_ns > 0
    assert local_dt.tzinfo is not None  # OS-provided tzinfo
    assert utc_dt.tzinfo == timezone.utc


def test_frozen_clock_deterministic():
    """Test FrozenClock returns fixed time."""
    # Create fixed time: 2026-03-15 10:30:00 (naive)
    frozen_dt = datetime(2026, 3, 15, 10, 30, 0)
    clock = FrozenClock(frozen_dt, frozen_mono_ns=5000000000)

    # Multiple calls return same value
    assert clock.now_unix_ms() == clock.now_unix_ms()
    assert clock.now_mono_ns() == 5000000000
    assert clock.now_local() == frozen_dt


def test_session_date_before_break():
    """Test session_date is current day before 17:00."""
    # Monday 16:59 → session_date = Monday
    frozen_dt = datetime(2026, 3, 16, 16, 59, 0)
    clock = FrozenClock(frozen_dt)
    session_mgr = SessionManager(clock=clock)

    session_date = session_mgr.session_date_iso(frozen_dt)

    assert session_date == "2026-03-16"  # Monday


def test_session_date_at_break_start():
    """Test session_date rolls to next day at 17:00 (break start)."""
    # Monday 17:00 → session_date = Tuesday
    frozen_dt = datetime(2026, 3, 16, 17, 0, 0)
    clock = FrozenClock(frozen_dt)
    session_mgr = SessionManager(clock=clock)

    session_date = session_mgr.session_date_iso(frozen_dt)

    assert session_date == "2026-03-17"  # Tuesday (next day)


def test_session_date_after_break():
    """Test session_date stays rolled after break (evening session)."""
    # Monday 18:00 → session_date = Tuesday
    frozen_dt = datetime(2026, 3, 16, 18, 0, 0)
    clock = FrozenClock(frozen_dt)
    session_mgr = SessionManager(clock=clock)

    session_date = session_mgr.session_date_iso(frozen_dt)

    assert session_date == "2026-03-17"  # Tuesday (next day)


def test_session_date_late_night():
    """Test session_date stays rolled late at night."""
    # Tuesday 02:00 → session_date = Tuesday
    frozen_dt = datetime(2026, 3, 17, 2, 0, 0)
    clock = FrozenClock(frozen_dt)
    session_mgr = SessionManager(clock=clock)

    session_date = session_mgr.session_date_iso(frozen_dt)

    assert session_date == "2026-03-17"  # Tuesday


def test_break_window_detection():
    """Test is_break_window detects 17:00-18:00."""
    session_mgr = SessionManager()

    # 16:59 → not in break
    dt_before = datetime(2026, 3, 16, 16, 59, 0)
    assert not session_mgr.is_break_window(dt_before)

    # 17:00 → in break
    dt_start = datetime(2026, 3, 16, 17, 0, 0)
    assert session_mgr.is_break_window(dt_start)

    # 17:30 → in break
    dt_mid = datetime(2026, 3, 16, 17, 30, 0)
    assert session_mgr.is_break_window(dt_mid)

    # 17:59 → in break
    dt_end_minus_1 = datetime(2026, 3, 16, 17, 59, 0)
    assert session_mgr.is_break_window(dt_end_minus_1)

    # 18:00 → not in break (session resumed)
    dt_after = datetime(2026, 3, 16, 18, 0, 0)
    assert not session_mgr.is_break_window(dt_after)


def test_operating_window_default():
    """Test in_operating_window with default 07:00-16:00."""
    session_mgr = SessionManager()

    # 06:59 → outside
    dt_before = datetime(2026, 3, 16, 6, 59, 0)
    assert not session_mgr.in_operating_window(dt_before)

    # 07:00 → inside
    dt_start = datetime(2026, 3, 16, 7, 0, 0)
    assert session_mgr.in_operating_window(dt_start)

    # 12:00 → inside
    dt_mid = datetime(2026, 3, 16, 12, 0, 0)
    assert session_mgr.in_operating_window(dt_mid)

    # 15:59 → inside
    dt_end_minus_1 = datetime(2026, 3, 16, 15, 59, 0)
    assert session_mgr.in_operating_window(dt_end_minus_1)

    # 16:00 → outside (end is exclusive)
    dt_after = datetime(2026, 3, 16, 16, 0, 0)
    assert not session_mgr.in_operating_window(dt_after)


def test_operating_window_custom():
    """Test in_operating_window with custom hours."""
    # Custom window: 09:00-14:00
    session_mgr = SessionManager(operating_start_hour=9, operating_end_hour=14)

    dt_before = datetime(2026, 3, 16, 8, 59, 0)
    assert not session_mgr.in_operating_window(dt_before)

    dt_start = datetime(2026, 3, 16, 9, 0, 0)
    assert session_mgr.in_operating_window(dt_start)

    dt_end = datetime(2026, 3, 16, 14, 0, 0)
    assert not session_mgr.in_operating_window(dt_end)


def test_session_phase_operating():
    """Test session_phase returns OPERATING during window."""
    session_mgr = SessionManager()
    dt = datetime(2026, 3, 16, 10, 0, 0)
    assert session_mgr.session_phase(dt) == "OPERATING"


def test_session_phase_break():
    """Test session_phase returns BREAK during 17:00-18:00."""
    session_mgr = SessionManager()
    dt = datetime(2026, 3, 16, 17, 30, 0)
    assert session_mgr.session_phase(dt) == "BREAK"


def test_session_phase_closed():
    """Test session_phase returns CLOSED outside hours."""
    session_mgr = SessionManager()
    dt = datetime(2026, 3, 16, 20, 0, 0)
    assert session_mgr.session_phase(dt) == "CLOSED"


def test_snapshot_dto_liveness_fields():
    """Test SnapshotDTO has liveness tracking fields."""
    snapshot = SnapshotDTO(
        run_id="test-run-123",
        snapshot_id=42,
        ts_unix_ms=1700000000000,
        ts_mono_ns=5000000000,
        last_any_event_mono_ns=4500000000,
        last_quote_event_mono_ns=4400000000,
        quotes_received_count=150,
    )

    # Verify liveness fields
    assert snapshot.last_any_event_mono_ns == 4500000000
    assert snapshot.last_quote_event_mono_ns == 4400000000
    assert snapshot.quotes_received_count == 150


def test_snapshot_dto_session_fields():
    """Test SnapshotDTO has session fields."""
    session = SessionDTO(
        in_operating_window=True,
        is_break_window=False,
        session_date_iso="2026-03-16",
    )

    snapshot = SnapshotDTO(
        run_id="test-run-456",
        snapshot_id=10,
        session=session,
    )

    # Verify session fields
    assert snapshot.session.in_operating_window is True
    assert snapshot.session.is_break_window is False
    assert snapshot.session.session_date_iso == "2026-03-16"


def test_snapshot_dto_quote_staleness():
    """Test QuoteDTO has staleness_ms field."""
    quote = QuoteDTO(
        bid=18500.0,
        ask=18500.25,
        ts_recv_mono_ns=5000000000,
        staleness_ms=150,  # 150ms stale
    )

    snapshot = SnapshotDTO(
        run_id="test-run-789",
        snapshot_id=20,
        quote=quote,
    )

    # Verify quote staleness
    assert snapshot.quote.staleness_ms == 150


def test_snapshot_dto_feed_degraded():
    """Test FeedDTO has degraded field."""
    feed = FeedDTO(
        connected=True,
        md_mode="DELAYED",
        degraded=True,  # Feed degraded due to delayed mode
        status_reason_codes=["MD_NOT_REALTIME"],
    )

    snapshot = SnapshotDTO(
        run_id="test-run-999",
        snapshot_id=30,
        feed=feed,
    )

    # Verify feed degraded
    assert snapshot.feed.degraded is True
    assert snapshot.feed.md_mode == "DELAYED"


def test_snapshot_dto_loop_health_fields():
    """Test LoopHealthDTO has all required fields."""
    loop = LoopHealthDTO(
        cycle_ms=12,
        cycle_overrun=False,
        engine_degraded=False,
        last_cycle_start_mono_ns=5000000000,
    )

    snapshot = SnapshotDTO(
        run_id="test-run-111",
        snapshot_id=40,
        loop=loop,
    )

    # Verify loop health fields
    assert snapshot.loop.cycle_ms == 12
    assert snapshot.loop.cycle_overrun is False
    assert snapshot.loop.engine_degraded is False
    assert snapshot.loop.last_cycle_start_mono_ns == 5000000000


def test_snapshot_dto_nested_structure():
    """Test SnapshotDTO uses nested DTO structure per spec."""
    snapshot = SnapshotDTO()

    # Verify nested DTOs exist and have correct types
    assert isinstance(snapshot.instrument, InstrumentDTO)
    assert isinstance(snapshot.feed, FeedDTO)
    assert isinstance(snapshot.quote, QuoteDTO)
    assert isinstance(snapshot.session, SessionDTO)
    assert isinstance(snapshot.controls, ControlsDTO)
    assert isinstance(snapshot.loop, LoopHealthDTO)
    assert isinstance(snapshot.gates, GatesDTO)


def test_snapshot_dto_immutability():
    """Test all DTOs are frozen (immutable)."""
    snapshot = SnapshotDTO(snapshot_id=100)

    # Attempt to modify should raise FrozenInstanceError
    with pytest.raises(Exception):  # dataclass.FrozenInstanceError
        snapshot.snapshot_id = 999

    with pytest.raises(Exception):
        snapshot.feed.connected = True

    with pytest.raises(Exception):
        snapshot.quote.bid = 18600.0


def test_session_date_rolls_across_days():
    """Test session_date rolls correctly across multiple days."""
    session_mgr = SessionManager()

    # Day 1: Before break (Monday 10:00)
    dt1 = datetime(2026, 3, 16, 10, 0, 0)
    assert session_mgr.session_date_iso(dt1) == "2026-03-16"

    # Day 1: After break (Monday 18:00)
    dt2 = datetime(2026, 3, 16, 18, 0, 0)
    assert session_mgr.session_date_iso(dt2) == "2026-03-17"  # Tuesday

    # Day 2: Before break (Tuesday 10:00)
    dt3 = datetime(2026, 3, 17, 10, 0, 0)
    assert session_mgr.session_date_iso(dt3) == "2026-03-17"  # Tuesday

    # Day 2: After break (Tuesday 18:00)
    dt4 = datetime(2026, 3, 17, 18, 0, 0)
    assert session_mgr.session_date_iso(dt4) == "2026-03-18"  # Wednesday


def test_liveness_age_computation():
    """Test liveness age can be computed from monotonic timestamps."""
    # Freeze time for deterministic test
    now_mono_ns = 10000000000  # 10 seconds
    last_quote_mono_ns = 8500000000  # 8.5 seconds

    # Age = now - last
    age_ns = now_mono_ns - last_quote_mono_ns
    age_ms = age_ns // 1_000_000

    assert age_ms == 1500  # 1.5 seconds = 1500ms


def test_quote_staleness_computation():
    """Test quote staleness can be computed from recv time."""
    # Quote received at: 5000ms
    # Current cycle time: 5200ms
    # Staleness = 200ms

    quote_recv_mono_ns = 5000 * 1_000_000
    cycle_mono_ns = 5200 * 1_000_000

    staleness_ns = cycle_mono_ns - quote_recv_mono_ns
    staleness_ms = staleness_ns // 1_000_000

    assert staleness_ms == 200


def test_clock_injection_for_session_manager():
    """Test SessionManager uses injected clock."""
    # Create frozen clock at specific time
    frozen_dt = datetime(2026, 3, 16, 17, 30, 0)
    frozen_clock = FrozenClock(frozen_dt)

    # SessionManager should use injected clock
    session_mgr = SessionManager(clock=frozen_clock)

    # Verify session_date_iso uses frozen clock when no arg provided
    assert session_mgr.session_date_iso() == "2026-03-17"  # Rolled (17:30 > 17:00)
    assert session_mgr.is_break_window() is True
    assert session_mgr.session_phase() == "BREAK"
