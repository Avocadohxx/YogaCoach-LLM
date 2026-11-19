"""Turn single-frame Tadasana comparisons into time-based evidence events.

One tracker instance is one ordered practice stream.  There is deliberately no
global tracker, session ID, pose ID, HTTP code, LLM call, or inferred confidence.
Use ``reset()`` when a new exercise stream starts, and a separate instance for
each simultaneous stream.  Callers must serialize calls to an individual
instance; this in-memory object is not shared between server processes.

Only a ``started`` lifecycle event sets feedback_allowed=True.  A recovered
event means the measured feature satisfied the clear condition; it does not
prove the complete posture is correct.  Missing/low-quality evidence interrupts
an event, and is never reported as improvement.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any
from uuid import uuid4


_STATUSES = {
    "deviation", "within_reference", "gray_zone", "not_assessable",
    "not_applicable", "disabled",
}
_PHASES = {"unknown", "prepare", "transition", "arms_down_hold", "arms_up_hold"}
_DEFAULT_TEMPORAL = {
    "min_duration_ms": 1500,
    "clear_duration_ms": 700,
    "max_gap_ms": 250,
}
_CONTEXT_KEYS = (
    "rule_version", "phase", "rules_reviewed", "execution_mode", "source_model",
    "phase_source", "phase_reviewed", "reference_status", "feature_version",
)


@dataclass
class _State:
    """Internal evidence for a pending or active rule, never returned directly."""

    tracking_state: str
    start_ms: int
    last_ms: int
    evidence: dict[str, Any]
    temporal: dict[str, int]
    context: dict[str, Any]
    event_id: str | None = None
    confirmed_ms: int | None = None
    clear_start_ms: int | None = None


def _require_int(value: Any, name: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        bound = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be a {bound} integer (not bool)")
    return value


def _check_finite(value: Any, path: str = "evaluation") -> None:
    """Reject NaN/Infinity even in optional, nested JSON evidence."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} must not contain NaN or Infinity")
    if isinstance(value, dict):
        for key, item in value.items():
            _check_finite(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_finite(item, f"{path}[{index}]")


def _validated_evaluation(
    evaluation: dict[str, Any], *, phases: set[str] | frozenset[str] = _PHASES,
) -> tuple[
    dict[str, Any], list[tuple[dict[str, Any], dict[str, int]]]
]:
    """Validate the full batch before any tracker state is mutated."""
    if not isinstance(evaluation, dict):
        raise ValueError("evaluation must be a dict")
    _check_finite(evaluation)
    frame = deepcopy(evaluation)
    _require_int(frame.get("timestamp_ms"), "timestamp_ms")
    if not isinstance(frame.get("rule_version"), str) or not frame["rule_version"].strip():
        raise ValueError("rule_version must be a non-empty string")
    if not isinstance(frame.get("phase"), str) or frame["phase"] not in phases:
        raise ValueError(f"phase must be one of {sorted(phases)}")
    if type(frame.get("rules_reviewed")) is not bool:
        raise ValueError("rules_reviewed must be bool")
    results = frame.get("rule_results")
    if not isinstance(results, list):
        raise ValueError("rule_results must be a list")
    normalized = []
    ids: set[str] = set()
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            raise ValueError(f"rule_results[{index}] must be a dict")
        for name in ("rule_id", "event_type", "target", "feature_name"):
            if not isinstance(result.get(name), str) or not result[name].strip():
                raise ValueError(f"rule_results[{index}].{name} must be a non-empty string")
        if result["rule_id"] in ids:
            raise ValueError(f"duplicate rule_id: {result['rule_id']}")
        ids.add(result["rule_id"])
        if not isinstance(result.get("status"), str) or result["status"] not in _STATUSES:
            raise ValueError(f"rule_results[{index}].status is unsupported")
        for name in ("observed_value", "comparison_value"):
            value = result.get(name)
            if value is not None and type(value) not in (int, float):
                raise ValueError(f"rule_results[{index}].{name} must be numeric or null (not bool)")
        reference_range = result.get("reference_range")
        if reference_range is not None and (
            not isinstance(reference_range, list)
            or len(reference_range) != 2
            or any(value is not None and type(value) not in (int, float) for value in reference_range)
            or (all(value is not None for value in reference_range)
                and reference_range[0] > reference_range[1])
        ):
            raise ValueError("reference_range must be an ordered numeric pair (null open bounds allowed) or null")
        temporal = dict(_DEFAULT_TEMPORAL)
        supplied = result.get("temporal", {})
        if not isinstance(supplied, dict):
            raise ValueError("temporal must be a dict")
        unknown = set(supplied) - set(temporal)
        if unknown:
            raise ValueError(f"unknown temporal keys: {sorted(unknown, key=str)}")
        temporal.update(supplied)
        for name, value in temporal.items():
            _require_int(value, f"temporal.{name}", positive=True)
        normalized.append((result, temporal))
    return frame, normalized


class TadasanaEventTracker:
    """Track rule continuity in one stream, using timestamps in milliseconds.

    ``update`` accepts the single-frame comparator's dict and returns a deep
    copy with new_events/active_events/pending_events/feedback_allowed/ignored.
    All single-frame rule evidence is retained.  ``duration_ms`` is calculated
    locally; any supplied duration/event_id/lifecycle field is overwritten.

    Temporal parameters are positive integers.  A gap is interrupted only when
    greater than max_gap_ms (equality remains continuous).  Confirm and recover
    thresholds are inclusive.  A pending gray-zone sample resets confirmation;
    an active gray-zone sample preserves the event and cancels recovery.

    Event duration_semantics is episode_elapsed: after activation, elapsed
    duration also includes tolerated gray-zone and recovery-confirmation time.
    It is not a sum of frames known to be outside a threshold.  At started,
    confirmation itself is based exclusively on consecutive deviation samples.

    rules_reviewed is provenance, not a policy gate: the comparator decides
    which rules are enabled.  Exploratory/unreviewed markers pass into events.
    """

    # Exercise-specific subclasses reuse the continuity engine while preserving
    # Tadasana's original phase vocabulary, provenance and event IDs by default.
    ALLOWED_PHASES = frozenset(_PHASES)
    CONTEXT_KEYS = _CONTEXT_KEYS
    EVENT_PREFIX = "tadasana"

    def __init__(self) -> None:
        self._instance_id = uuid4().hex[:12]
        self._next_id = 0
        self._states: dict[str, _State] = {}
        self._last_timestamp_ms: int | None = None
        self._phase: str | None = None
        self._rule_version: str | None = None
        self._context_signature: dict[str, Any] | None = None

    def reset(self) -> None:
        """Forget continuity and timestamps, without ever reusing event IDs.

        This explicit new-stream operation has no timestamp and emits no
        recovered claim.  A caller needing an interruption record should first
        submit a final frame with rules not_applicable/disabled.
        """
        self._states.clear()
        self._last_timestamp_ms = None
        self._phase = None
        self._rule_version = None
        self._context_signature = None

    @staticmethod
    def _event(
        state: _State, status: str, timestamp_ms: int, *, reason: str | None = None,
        effective_end_ms: int | None = None,
    ) -> dict[str, Any]:
        event = deepcopy(state.evidence)
        event["rule_status"] = event["status"]
        event.update(deepcopy(state.context))
        event.update({
            "status": status,
            "tracking_state": state.tracking_state,
            "timestamp_ms": timestamp_ms,
            "start_timestamp_ms": state.start_ms,
            "confirmed_timestamp_ms": state.confirmed_ms,
            "duration_ms": (state.last_ms if effective_end_ms is None else effective_end_ms) - state.start_ms,
            "duration_semantics": "episode_elapsed",
        })
        # Never accept lifecycle identity/time from a single-frame payload.
        event.pop("event_id", None)
        event.pop("end_timestamp_ms", None)
        event.pop("interruption_reason", None)
        if state.event_id is not None:
            event["event_id"] = state.event_id
        if status in {"recovered", "interrupted"}:
            event["end_timestamp_ms"] = state.last_ms if effective_end_ms is None else effective_end_ms
        if reason is not None:
            event["interruption_reason"] = reason
        return event

    def _interrupt(self, rule_id: str, timestamp_ms: int, reason: str) -> dict[str, Any] | None:
        state = self._states.pop(rule_id)
        if state.event_id is None:
            return None
        return self._event(state, "interrupted", timestamp_ms, reason=reason)

    def update(self, evaluation: dict[str, Any]) -> dict[str, Any]:
        frame, results = _validated_evaluation(evaluation, phases=self.ALLOWED_PHASES)
        timestamp_ms = frame["timestamp_ms"]
        frame.update({
            "new_events": [], "active_events": [], "pending_events": [],
            "feedback_allowed": False, "ignored": False, "ignored_reason": None,
        })
        if self._last_timestamp_ms is not None and timestamp_ms <= self._last_timestamp_ms:
            frame["ignored"] = True
            frame["ignored_reason"] = (
                "duplicate_timestamp" if timestamp_ms == self._last_timestamp_ms
                else "out_of_order_timestamp"
            )
            # No lifecycle output from old input; absolutely no state changes.
            return frame

        events = frame["new_events"]
        change_reason = None
        if self._phase is not None and frame["phase"] != self._phase:
            change_reason = "phase_changed"
        elif self._rule_version is not None and frame["rule_version"] != self._rule_version:
            change_reason = "rule_version_changed"
        # Missing and explicitly null context fields have the same signature.
        # Never relabel existing unreviewed/source-specific evidence in place.
        signature = {key: deepcopy(frame.get(key)) for key in self.CONTEXT_KEYS}
        if (
            change_reason is None
            and self._context_signature is not None
            and signature != self._context_signature
        ):
            change_reason = "context_changed"
        if change_reason:
            for rule_id in list(self._states):
                interrupted = self._interrupt(rule_id, timestamp_ms, change_reason)
                if interrupted:
                    events.append(interrupted)

        self._phase = frame["phase"]
        self._rule_version = frame["rule_version"]
        self._context_signature = signature
        context = {key: deepcopy(frame[key]) for key in self.CONTEXT_KEYS if key in frame}
        present_ids = {result["rule_id"] for result, _ in results}
        for rule_id in list(self._states):
            if rule_id not in present_ids:
                interrupted = self._interrupt(rule_id, timestamp_ms, "rule_missing")
                if interrupted:
                    events.append(interrupted)

        for result, temporal in results:
            rule_id = result["rule_id"]
            status = result["status"]
            state = self._states.get(rule_id)
            reason = None
            if state is not None and timestamp_ms - state.last_ms > state.temporal["max_gap_ms"]:
                reason = "frame_gap"
            elif state is not None and temporal != state.temporal:
                reason = "temporal_parameters_changed"
            if reason:
                interrupted = self._interrupt(rule_id, timestamp_ms, reason)
                if interrupted:
                    events.append(interrupted)
                state = None

            if status in {"not_assessable", "not_applicable", "disabled"}:
                if state is not None:
                    interrupted = self._interrupt(rule_id, timestamp_ms, status)
                    if interrupted:
                        events.append(interrupted)
                continue

            if state is None:
                if status == "deviation":
                    self._states[rule_id] = _State(
                        tracking_state="pending", start_ms=timestamp_ms, last_ms=timestamp_ms,
                        evidence=deepcopy(result), temporal=temporal, context=deepcopy(context),
                    )
                continue

            if state.tracking_state == "pending":
                if status != "deviation":
                    del self._states[rule_id]
                    continue
                state.last_ms = timestamp_ms
                state.evidence = deepcopy(result)
                state.context = deepcopy(context)
                if timestamp_ms - state.start_ms >= temporal["min_duration_ms"]:
                    self._next_id += 1
                    state.event_id = f"{self.EVENT_PREFIX}-{self._instance_id}-{self._next_id:06d}"
                    state.confirmed_ms = timestamp_ms
                    state.tracking_state = "active"
                    events.append(self._event(state, "started", timestamp_ms))
                continue

            # An active event can enter/leave recovery confirmation without a
            # new identity. Gray-zone evidence is insufficient to clear it.
            state.last_ms = timestamp_ms
            state.evidence = deepcopy(result)
            state.context = deepcopy(context)
            if status == "within_reference":
                if state.clear_start_ms is None:
                    state.clear_start_ms = timestamp_ms
                state.tracking_state = "clearing"
                if timestamp_ms - state.clear_start_ms >= temporal["clear_duration_ms"]:
                    events.append(self._event(state, "recovered", timestamp_ms))
                    del self._states[rule_id]
            else:
                state.clear_start_ms = None
                state.tracking_state = "active"

        self._last_timestamp_ms = timestamp_ms
        for state in self._states.values():
            if state.event_id is None:
                frame["pending_events"].append(self._event(state, "pending", timestamp_ms))
            else:
                frame["active_events"].append(self._event(state, "active", timestamp_ms))
        frame["feedback_allowed"] = any(event["status"] == "started" for event in events)
        return frame
