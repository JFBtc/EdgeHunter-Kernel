"""
Clock & Time Utility - V1a J2

Provides canonical time semantics with timezone support (America/Montreal).

Responsibilities:
- Wall-clock time (UTC and local)
- Monotonic time for staleness/age calculations
- Session date computation (rolls at 17:00 ET)
- Operating window and break window detection
- Deterministic clock injection for testing

Architecture:
- Default implementation uses real system time
- Test implementations can inject frozen/mock time
- All staleness calculations use monotonic time only
"""
import time
from datetime import datetime, timedelta
from typing import Optional, Protocol
from zoneinfo import ZoneInfo


# Timezone constant (America/Montreal = America/Toronto per V1a spec)
TIMEZONE_LOCAL = ZoneInfo("America/Montreal")


class ClockProtocol(Protocol):
    """
    Protocol for clock implementations (real or mock).

    Allows deterministic testing by injecting fake time.
    """

    def now_unix_ms(self) -> int:
        """Wall-clock time in milliseconds since epoch (UTC)."""
        ...

    def now_mono_ns(self) -> int:
        """Monotonic time in nanoseconds (for age/staleness)."""
        ...

    def now_local(self) -> datetime:
        """Current time in America/Montreal timezone."""
        ...

    def now_utc(self) -> datetime:
        """Current time in UTC timezone."""
        ...


class SystemClock:
    """
    Real system clock implementation.

    Uses time.time() for wall-clock and time.perf_counter_ns() for monotonic.
    """

    def now_unix_ms(self) -> int:
        """Wall-clock time in milliseconds since epoch (UTC)."""
        return int(time.time() * 1000)

    def now_mono_ns(self) -> int:
        """Monotonic time in nanoseconds (for age/staleness)."""
        return time.perf_counter_ns()

    def now_local(self) -> datetime:
        """Current time in America/Montreal timezone."""
        return datetime.now(TIMEZONE_LOCAL)

    def now_utc(self) -> datetime:
        """Current time in UTC timezone."""
        return datetime.now(ZoneInfo("UTC"))


class SessionManager:
    """
    Session & window manager for V1a futures trading.

    Session semantics:
    - 23-hour session with 1-hour break
    - Break window: 17:00-18:00 ET daily
    - Session start: 18:00 ET (evening)
    - Session date rolls at 17:00 ET (break start)
    - Operating window: configurable (default 07:00-16:00 ET)

    Example session timeline (America/Montreal time):
    - Monday 18:00 → Tuesday 17:00 (session_date = Tuesday)
    - 17:00-18:00: break window (is_break_window=True)
    - Tuesday 18:00 → Wednesday 17:00 (session_date = Wednesday)
    """

    def __init__(
        self,
        clock: Optional[ClockProtocol] = None,
        operating_start_hour: int = 7,  # 07:00 ET
        operating_end_hour: int = 16,   # 16:00 ET (before break)
    ):
        """
        Initialize session manager.

        Args:
            clock: Clock implementation (defaults to SystemClock)
            operating_start_hour: Start of operating window (ET hour)
            operating_end_hour: End of operating window (ET hour, exclusive)
        """
        self.clock = clock or SystemClock()
        self.operating_start_hour = operating_start_hour
        self.operating_end_hour = operating_end_hour

        # Break window constants
        self.break_start_hour = 17  # 17:00 ET
        self.break_end_hour = 18    # 18:00 ET

    def session_date_iso(self, now_local: Optional[datetime] = None) -> str:
        """
        Compute session date (rolls at 17:00 ET).

        Session date logic:
        - If before 17:00 ET: session_date = current calendar date
        - If 17:00 ET or after: session_date = next calendar date

        Args:
            now_local: Current local time (defaults to clock.now_local())

        Returns:
            ISO date string (YYYY-MM-DD)

        Examples:
            - Monday 16:59 ET → Monday
            - Monday 17:00 ET → Tuesday (break started, next session)
            - Monday 18:00 ET → Tuesday (session running)
            - Tuesday 16:59 ET → Tuesday
            - Tuesday 17:00 ET → Wednesday
        """
        if now_local is None:
            now_local = self.clock.now_local()

        # Roll session date if at or past break start (17:00 ET)
        if now_local.hour >= self.break_start_hour:
            # Session date is tomorrow
            session_dt = now_local + timedelta(days=1)
        else:
            # Session date is today
            session_dt = now_local

        return session_dt.date().isoformat()

    def is_break_window(self, now_local: Optional[datetime] = None) -> bool:
        """
        Check if current time is in break window (17:00-18:00 ET).

        Args:
            now_local: Current local time (defaults to clock.now_local())

        Returns:
            True if in break window (17:00 <= hour < 18:00)
        """
        if now_local is None:
            now_local = self.clock.now_local()

        return self.break_start_hour <= now_local.hour < self.break_end_hour

    def in_operating_window(self, now_local: Optional[datetime] = None) -> bool:
        """
        Check if current time is in configured operating window.

        Args:
            now_local: Current local time (defaults to clock.now_local())

        Returns:
            True if in operating window (start_hour <= hour < end_hour)
        """
        if now_local is None:
            now_local = self.clock.now_local()

        return self.operating_start_hour <= now_local.hour < self.operating_end_hour

    def session_phase(self, now_local: Optional[datetime] = None) -> str:
        """
        Compute session phase (OPERATING | BREAK | CLOSED).

        Args:
            now_local: Current local time (defaults to clock.now_local())

        Returns:
            Phase string: "OPERATING" | "BREAK" | "CLOSED"
        """
        if now_local is None:
            now_local = self.clock.now_local()

        if self.is_break_window(now_local):
            return "BREAK"
        elif self.in_operating_window(now_local):
            return "OPERATING"
        else:
            return "CLOSED"


# Global default clock instance (can be replaced for testing)
_default_clock: ClockProtocol = SystemClock()


def get_default_clock() -> ClockProtocol:
    """Get the global default clock instance."""
    return _default_clock


def set_default_clock(clock: ClockProtocol) -> None:
    """
    Set the global default clock instance.

    Used for testing to inject mock/frozen time.

    Args:
        clock: Clock implementation to use as default
    """
    global _default_clock
    _default_clock = clock


# Convenience functions using default clock
def now_unix_ms() -> int:
    """Wall-clock time in milliseconds since epoch (UTC)."""
    return _default_clock.now_unix_ms()


def now_mono_ns() -> int:
    """Monotonic time in nanoseconds (for age/staleness)."""
    return _default_clock.now_mono_ns()


def now_local() -> datetime:
    """Current time in America/Montreal timezone."""
    return _default_clock.now_local()


def now_utc() -> datetime:
    """Current time in UTC timezone."""
    return _default_clock.now_utc()
