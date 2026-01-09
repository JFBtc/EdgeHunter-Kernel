"""
Tests for V1a J4 - SnapshotDTO v1 Contract + Invariants

Validates:
- Schema version is exactly "snapshot.v1"
- Atomic publication (copy-on-write, no partial updates)
- Monotonic snapshot_id
- Invariants: ready==allowed AND ready_reasons==reason_codes in every snapshot
"""
import time
import pytest

from src.datahub import DataHub
from src.engine import EngineLoop
from src.snapshot import SnapshotDTO


def test_j4_schema_version_snapshot_v1():
    """Test every published snapshot has schema_version == 'snapshot.v1'."""
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)

    try:
        engine.start()
        time.sleep(0.3)  # Allow multiple cycles

        # Collect snapshots
        for _ in range(20):
            snapshot = datahub.get_latest()
            if snapshot:
                assert snapshot.schema_version == "snapshot.v1", (
                    f"Schema version must be 'snapshot.v1', got '{snapshot.schema_version}'"
                )
            time.sleep(0.03)

    finally:
        engine.stop()


def test_j4_invariant_ready_equals_allowed():
    """
    Test J4 invariant: ready == gates.allowed in every published snapshot.

    V1a requirement: ready field must always equal gates.allowed.
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)

    try:
        engine.start()
        time.sleep(0.3)

        violations = []

        # Check invariant across multiple snapshots
        for i in range(30):
            snapshot = datahub.get_latest()
            if snapshot:
                if snapshot.ready != snapshot.gates.allowed:
                    violations.append({
                        "snapshot_id": snapshot.snapshot_id,
                        "ready": snapshot.ready,
                        "allowed": snapshot.gates.allowed,
                    })
            time.sleep(0.02)

        # Assert no violations
        assert len(violations) == 0, (
            f"Invariant violation: ready != gates.allowed in {len(violations)} snapshots: {violations}"
        )

    finally:
        engine.stop()


def test_j4_invariant_ready_reasons_equals_reason_codes():
    """
    Test J4 invariant: ready_reasons == gates.reason_codes in every published snapshot.

    V1a requirement: ready_reasons field must always equal gates.reason_codes.
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)

    try:
        engine.start()
        time.sleep(0.3)

        violations = []

        # Check invariant across multiple snapshots
        for i in range(30):
            snapshot = datahub.get_latest()
            if snapshot:
                if snapshot.ready_reasons != snapshot.gates.reason_codes:
                    violations.append({
                        "snapshot_id": snapshot.snapshot_id,
                        "ready_reasons": snapshot.ready_reasons,
                        "reason_codes": snapshot.gates.reason_codes,
                    })
            time.sleep(0.02)

        # Assert no violations
        assert len(violations) == 0, (
            f"Invariant violation: ready_reasons != gates.reason_codes in {len(violations)} snapshots: {violations}"
        )

    finally:
        engine.stop()


def test_j4_combined_invariants():
    """
    Test both J4 invariants together across multiple snapshots.

    Validates:
    - ready == gates.allowed
    - ready_reasons == gates.reason_codes
    - Schema version is "snapshot.v1"
    - snapshot_id is monotonic
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)

    try:
        engine.start()
        time.sleep(0.4)

        snapshots = []
        for _ in range(40):
            snapshot = datahub.get_latest()
            if snapshot and (not snapshots or snapshot.snapshot_id != snapshots[-1].snapshot_id):
                snapshots.append(snapshot)
            time.sleep(0.02)

        # Verify we collected multiple distinct snapshots
        assert len(snapshots) >= 5, f"Expected at least 5 snapshots, got {len(snapshots)}"

        # Verify all invariants for each snapshot
        for snapshot in snapshots:
            # J4 Invariant 1: ready == gates.allowed
            assert snapshot.ready == snapshot.gates.allowed, (
                f"Snapshot {snapshot.snapshot_id}: ready ({snapshot.ready}) != allowed ({snapshot.gates.allowed})"
            )

            # J4 Invariant 2: ready_reasons == gates.reason_codes
            assert snapshot.ready_reasons == snapshot.gates.reason_codes, (
                f"Snapshot {snapshot.snapshot_id}: ready_reasons ({snapshot.ready_reasons}) != reason_codes ({snapshot.gates.reason_codes})"
            )

            # Schema version
            assert snapshot.schema_version == "snapshot.v1", (
                f"Snapshot {snapshot.snapshot_id}: schema_version must be 'snapshot.v1', got '{snapshot.schema_version}'"
            )

        # Verify monotonic snapshot_id
        for i in range(1, len(snapshots)):
            assert snapshots[i].snapshot_id > snapshots[i - 1].snapshot_id, (
                f"Snapshot IDs not monotonic: {snapshots[i].snapshot_id} <= {snapshots[i-1].snapshot_id}"
            )

    finally:
        engine.stop()


def test_j4_snapshot_immutability():
    """
    Test that SnapshotDTO is immutable (frozen dataclass).

    J4 requirement: Snapshots must not be mutated after publication.
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=100)

    try:
        engine.start()
        time.sleep(0.2)

        snapshot = datahub.get_latest()
        assert snapshot is not None

        # Attempt to mutate top-level fields should fail
        with pytest.raises(Exception):  # FrozenInstanceError
            snapshot.snapshot_id = 999  # type: ignore

        with pytest.raises(Exception):
            snapshot.ready = True  # type: ignore

        with pytest.raises(Exception):
            snapshot.schema_version = "snapshot.v2"  # type: ignore

        # Nested DTOs should also be immutable
        with pytest.raises(Exception):
            snapshot.gates.allowed = True  # type: ignore

        with pytest.raises(Exception):
            snapshot.controls.intent = "LONG"  # type: ignore

    finally:
        engine.stop()


def test_j4_atomic_publication_no_partial_state():
    """
    Test that atomic publication prevents partial state observation.

    J4 requirement: Readers must never observe snapshots with inconsistent
    ready/allowed or ready_reasons/reason_codes.
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=30)

    try:
        engine.start()
        time.sleep(0.5)

        # Rapidly read snapshots and verify consistency
        for _ in range(100):
            snapshot = datahub.get_latest()
            if snapshot:
                # If we can read a snapshot, it must be fully consistent
                assert snapshot.ready == snapshot.gates.allowed, (
                    "Observed partial state: ready != gates.allowed"
                )
                assert snapshot.ready_reasons == snapshot.gates.reason_codes, (
                    "Observed partial state: ready_reasons != gates.reason_codes"
                )
                assert snapshot.schema_version == "snapshot.v1", (
                    "Observed partial state: invalid schema_version"
                )
            time.sleep(0.001)  # Tight loop to stress-test atomicity

    finally:
        engine.stop()


def test_j4_snapshot_fields_complete():
    """
    Test that every published snapshot has all required v1 fields present.

    J4 requirement: Schema contract guarantees all v1 fields exist.
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)

    try:
        engine.start()
        time.sleep(0.2)

        snapshot = datahub.get_latest()
        assert snapshot is not None

        # Verify top-level fields
        assert hasattr(snapshot, "schema_version")
        assert hasattr(snapshot, "run_id")
        assert hasattr(snapshot, "snapshot_id")
        assert hasattr(snapshot, "cycle_count")
        assert hasattr(snapshot, "ts_unix_ms")
        assert hasattr(snapshot, "ts_mono_ns")

        # Verify nested DTOs
        assert hasattr(snapshot, "instrument")
        assert hasattr(snapshot, "feed")
        assert hasattr(snapshot, "quote")
        assert hasattr(snapshot, "session")
        assert hasattr(snapshot, "controls")
        assert hasattr(snapshot, "loop")
        assert hasattr(snapshot, "gates")

        # Verify liveness fields
        assert hasattr(snapshot, "last_any_event_mono_ns")
        assert hasattr(snapshot, "last_quote_event_mono_ns")
        assert hasattr(snapshot, "quotes_received_count")

        # Verify ready mapping fields
        assert hasattr(snapshot, "ready")
        assert hasattr(snapshot, "ready_reasons")

        # Verify extras
        assert hasattr(snapshot, "extras")

        # Verify all nested DTOs have expected fields
        assert hasattr(snapshot.controls, "intent")
        assert hasattr(snapshot.controls, "arm")
        assert hasattr(snapshot.controls, "last_cmd_id")
        assert hasattr(snapshot.controls, "last_cmd_ts_unix_ms")

        assert hasattr(snapshot.gates, "allowed")
        assert hasattr(snapshot.gates, "reason_codes")
        assert hasattr(snapshot.gates, "gate_metrics")

    finally:
        engine.stop()


def test_j4_monotonic_snapshot_id_strict():
    """
    Test strict monotonic increase of snapshot_id.

    J4 requirement: snapshot_id must increase by exactly 1 per cycle.
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)

    try:
        engine.start()
        time.sleep(0.5)

        # Collect unique snapshots
        snapshots = []
        for _ in range(30):
            snapshot = datahub.get_latest()
            if snapshot and (not snapshots or snapshot.snapshot_id != snapshots[-1].snapshot_id):
                snapshots.append(snapshot)
            time.sleep(0.05)

        # Verify at least 5 distinct snapshots
        assert len(snapshots) >= 5, f"Expected at least 5 snapshots, got {len(snapshots)}"

        # Verify strict monotonic increase
        for i in range(1, len(snapshots)):
            prev_id = snapshots[i - 1].snapshot_id
            curr_id = snapshots[i].snapshot_id
            assert curr_id == prev_id + 1, (
                f"Snapshot IDs not consecutive: {prev_id} -> {curr_id}"
            )

    finally:
        engine.stop()


def test_j4_copy_on_write_semantics():
    """
    Test that each cycle creates a NEW SnapshotDTO instance.

    J4 requirement: Copy-on-write means each publish creates a new object.
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)

    try:
        engine.start()
        time.sleep(0.3)

        # Collect snapshot instances
        snapshot_instances = []
        seen_ids = set()

        for _ in range(20):
            snapshot = datahub.get_latest()
            if snapshot and snapshot.snapshot_id not in seen_ids:
                snapshot_instances.append(snapshot)
                seen_ids.add(snapshot.snapshot_id)
            time.sleep(0.05)

        # Verify we have multiple snapshots
        assert len(snapshot_instances) >= 3, (
            f"Expected at least 3 snapshots, got {len(snapshot_instances)}"
        )

        # Verify each snapshot is a distinct object instance
        for i in range(1, len(snapshot_instances)):
            assert snapshot_instances[i] is not snapshot_instances[i - 1], (
                f"Snapshot {snapshot_instances[i].snapshot_id} is same object as previous"
            )

    finally:
        engine.stop()
