"""Persistent standing-side-bend evidence, sharing the Tadasana state machine.

Create one instance for one ordered practice stream and call ``reset()`` when
starting a new stream.  There are no session/pose IDs, global state, camera
capture, HTTP calls, or LLM calls here.  The caller must serialize updates.

The comparator decides which rules are applicable, reviewed and enabled.  This
class only confirms continuous evidence: deviation -> pending -> started;
stable clear evidence -> recovered; unavailable evidence or changed context ->
interrupted.  Gray-zone evidence never counts as recovery.  Only newly started
events make the returned ``feedback_allowed`` true.

Directions use image coordinates (image_left/image_right), not anatomical left
and right.  A direction, camera, movement variant, or review/source change
interrupts the old event with its original provenance before counting the new
context.  Switching sides must never be mistaken for correcting a deviation.
"""

from __future__ import annotations

from backend.tadasana_event_tracker import TadasanaEventTracker


class ArdhakatiEventTracker(TadasanaEventTracker):
    """One side-bend practice stream; ``update`` and ``reset`` match Tadasana.

    Per-rule temporal values are read from the single-frame result.  The draft
    side-bend rules supply 1500 ms to confirm, 700 ms to recover and a 500 ms
    maximum frame gap.  ``duration_ms`` is episode elapsed time, not accumulated
    time strictly outside a threshold.  Review flags remain evidence provenance;
    unreviewed rules must be disabled by the comparator unless preview is
    explicitly enabled.
    """

    ALLOWED_PHASES = TadasanaEventTracker.ALLOWED_PHASES | {
        "side_bend_hold", "return_upright",
    }
    CONTEXT_KEYS = TadasanaEventTracker.CONTEXT_KEYS + (
        "exercise", "bend_direction", "direction_source", "direction_reviewed",
        "camera_view", "camera_view_verified", "camera_view_source",
        "movement_variant", "variant_reviewed", "variant_source",
        "raised_arm_side", "raised_arm_source", "raised_arm_reviewed",
    )
    EVENT_PREFIX = "ardhakati"
