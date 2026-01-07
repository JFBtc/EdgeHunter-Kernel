"""
Tests for V1a J2 - Time + Liveness + Session Windows

Validates:
- Clock/Time utility with timezone support
- Session date computation (rolls at 17:00 ET)
- Operating window and break window detection
- Liveness tracking fields
- Deterministic clock injection for testing
"""
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.clock import (
    SystemClock,
    SessionManager,
    TIMEZONE_LOCAL,
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
    """

    def __init__(
        self,
        frozen_dt: datetime,
        frozen_mono_ns: int = 1000000000,  # 1 second
    ):
        """
        Initialize frozen clock.

        Args:
            frozen_dt: Fixed datetime (must be timezone-aware)
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
        """Current time in America/Montreal timezone."""
        return self.frozen_dt.astimezone(TIMEZONE_LOCAL)

    def now_utc(self) -> datetime:
        """Current time in UTC timezone."""
        return self.frozen_dt.astimezone(ZoneInfo("UTC"))


# Test fixtures for common times
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
    assert local_dt.tzinfo == TIMEZONE_LOCAL
    assert utc_dt.tzinfo == ZoneInfo("UTC")


def test_frozen_clock_deterministic():
    """Test FrozenClock returns fixed time."""
    # Create fixed time: 2026-03-15 10:30:00 ET
    frozen_dt = datetime(2026, 3, 15, 10, 30, 0, tzinfo=TIMEZONE_LOCAL)
    clock = FrozenClock(frozen_dt, frozen_mono_ns=5000000000)

    # Multiple calls return same value
    assert clock.now_unix_ms() == clock.now_unix_ms()
    assert clock.now_mono_ns() == 5000000000
    assert clock.now_local() == frozen_dt


def test_session_date_before_break():
    """Test session_date is current day before 17:00 ET."""
    # Monday 16:59 ET → session_date = Monday
    frozen_dt = datetime(2026, 3, 16, 16, 59, 0, tzinfo=TIMEZONE_LOCAL)
    clock = FrozenClock(frozen_dt)
    session_mgr = SessionManager(clock=clock)

    session_date = session_mgr.session_date_iso()

    assert session_date == "2026-03-16"  # Monday


def test_session_date_at_break_start():
    """Test session_date rolls to next day at 17:00 ET (break start)."""
    # Monday 17:00 ET → session_date = Tuesday
    frozen_dt = datetime(2026, 3, 16, 17, 0, 0, tzinfo=TIMEZONE_LOCAL)
    clock = FrozenClock(frozen_dt)
    session_mgr = SessionManager(clock=clock)

    session_date = session_mgr.session_date_iso()

    assert session_date == "2026-03-17"  # Tuesday (next day)


def test_session_date_after_break():
    """Test session_date stays rolled after break (evening session)."""
    # Monday 18:00 ET → session_date = Tuesday
    frozen_dt = datetime(2026, 3, 16, 18, 0, 0, tzinfo=TIMEZONE_LOCAL)
    clock = FrozenClock(frozen_dt)
    session_mgr = SessionManager(clock=clock)

    session_date = session_mgr.session_date_iso()

    assert session_date == "2026-03-17"  # Tuesday (next day)


def test_session_date_late_night():
    """Test session_date stays rolled late at night."""
    # Tuesday 02:00 ET → session_date = Tuesday
    frozen_dt = datetime(2026, 3, 17, 2, 0, 0, tzinfo=TIMEZONE_LOCAL)
    clock = FrozenClock(frozen_dt)
    session_mgr = SessionManager(clock=clock)

    session_date = session_mgr.session_date_iso()

    assert session_date == "2026-03-17"  # Tuesday


def test_break_window_detection():
    """Test is_break_window detects 17:00-18:00 ET."""
    session_mgr = SessionManager()

    # 16:59 ET → not in break
    dt_before = datetime(2026, 3, 16, 16, 59, 0, tzinfo=TIMEZONE_LOCAL)
    assert not session_mgr.is_break_window(dt_before)

    # 17:00 ET → in break
    dt_start = datetime(2026, 3, 16, 17, 0, 0, tzinfo=TIMEZONE_LOCAL)
    assert session_mgr.is_break_window(dt_start)

    # 17:30 ET → in break
    dt_mid = datetime(2026, 3, 16, 17, 30, 0, tzinfo=TIMEZONE_LOCAL)
    assert session_mgr.is_break_window(dt_mid)

    # 17:59 ET → in break
    dt_end_minus_1 = datetime(2026, 3, 16, 17, 59, 0, tzinfo=TIMEZONE_LOCAL)
    assert session_mgr.is_break_window(dt_end_minus_1)

    # 18:00 ET → not in break (session resumed)
    dt_after = datetime(2026, 3, 16, 18, 0, 0, tzinfo=TIMEZONE_LOCAL)
    assert not session_mgr.is_break_window(dt_after)


def test_operating_window_default():
    """Test in_operating_window with default 07:00-16:00 ET."""
    session_mgr = SessionManager()

    # 06:59 ET → outside
    dt_before = datetime(2026, 3, 16, 6, 59, 0, tzinfo=TIMEZONE_LOCAL)
    assert not session_mgr.in_operating_window(dt_before)

    # 07:00 ET → inside
    dt_start = datetime(2026, 3, 16, 7, 0, 0, tzinfo=TIMEZONE_LOCAL)
    assert session_mgr.in_operating_window(dt_start)

    # 12:00 ET → inside
    dt_mid = datetime(2026, 3, 16, 12, 0, 0, tzinfo=TIMEZONE_LOCAL)
    assert session_mgr.in_operating_window(dt_mid)

    # 15:59 ET → inside
    dt_end_minus_1 = datetime(2026, 3, 16, 15, 59, 0, tzinfo=TIMEZONE_LOCAL)
    assert session_mgr.in_operating_window(dt_end_minus_1)

    # 16:00 ET → outside (end is exclusive)
    dt_after = datetime(2026, 3, 16, 16, 0, 0, tzinfo=TIMEZONE_LOCAL)
    assert not session_mgr.in_operating_window(dt_after)


def test_operating_window_custom():
    """Test in_operating_window with custom hours."""
    # Custom window: 09:00-14:00 ET
    session_mgr = SessionManager(operating_start_hour=9, operating_end_hour=14)

    dt_before = datetime(2026, 3, 16, 8, 59, 0, tzinfo=TIMEZONE_LOCAL)
    assert not session_mgr.in_operating_window(dt_before)

    dt_start = datetime(2026, 3, 16, 9, 0, 0, tzinfo=TIMEZONE_LOCAL)
    assert session_mgr.in_operating_window(dt_start)

    dt_end = datetime(2026, 3, 16, 14, 0, 0, tzinfo=TIMEZONE_LOCAL)
    assert not session_mgr.in_operating_window(dt_end)


def test_session_phase_operating():
    """Test session_phase returns OPERATING during window."""
    session_mgr = SessionManager()
    dt = datetime(2026, 3, 16, 10, 0, 0, tzinfo=TIMEZONE_LOCAL)
    assert session_mgr.session_phase(dt) == "OPERATING"


def test_session_phase_break():
    """Test session_phase returns BREAK during 17:00-18:00."""
    session_mgr = SessionManager()
    dt = datetime(2026, 3, 16, 17, 30, 0, tzinfo=TIMEZONE_LOCAL)
    assert session_mgr.session_phase(dt) == "BREAK"


def test_session_phase_closed():
    """Test session_phase returns CLOSED outside hours."""
    session_mgr = SessionManager()
    dt = datetime(2026, 3, 16, 20, 0, 0, tzinfo=TIMEZONE_LOCAL)
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


def test_session_manager_dst_transition():
    """Test session_date_iso handles DST transitions correctly."""
    session_mgr = SessionManager()

    # Test around DST transition (spring forward: 2026-03-08 02:00 → 03:00)
    # Day before DST: March 7, 16:00 ET (EST)
    dt_before_dst = datetime(2026, 3, 7, 16, 0, 0, tzinfo=TIMEZONE_LOCAL)
    assert session_mgr.session_date_iso(dt_before_dst) == "2026-03-07"

    # DST transition day: March 8, 16:00 ET (EDT now)
    dt_after_dst = datetime(2026, 3, 8, 16, 0, 0, tzinfo=TIMEZONE_LOCAL)
    assert session_mgr.session_date_iso(dt_after_dst) == "2026-03-08"

    # DST transition day evening: March 8, 18:00 EDT
    dt_after_dst_evening = datetime(2026, 3, 8, 18, 0, 0, tzinfo=TIMEZONE_LOCAL)
    assert session_mgr.session_date_iso(dt_after_dst_evening) == "2026-03-09"


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
