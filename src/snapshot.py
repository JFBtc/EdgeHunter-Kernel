"""
SnapshotDTO - Atomic snapshot schema (snapshot.v1)
V1a.1 Slice 1: Minimal skeleton with placeholders
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SnapshotDTO:
    """
    Immutable snapshot published atomically by the engine loop.
    Schema version: snapshot.v1

    V1a.1 Slice 1: Contains minimal fields for loop health and gates.
    Quote fields are placeholders (None) - no feed yet.
    """
    # Schema metadata
    schema_version: str = "snapshot.v1"

    # Run identity
    run_id: str = ""
    snapshot_id: int = 0
    ts_unix_ms: int = 0

    # Controls (minimal)
    intent: str = "FLAT"  # LONG|SHORT|BOTH|FLAT
    arm: bool = False

    # Gates output
    allowed: bool = False
    reason_codes: list[str] = field(default_factory=list)

    # Loop health
    cycle_ms: int = 0
    engine_degraded: bool = False

    # Quote (placeholders for Slice 1 - no feed yet)
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    spread_ticks: Optional[int] = None
    staleness_ms: Optional[int] = None

    # Reserved for future extensions
    extras: dict = field(default_factory=dict)
