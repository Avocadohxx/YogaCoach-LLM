"""Bounded, short-lived server analysis snapshots (single-worker MVP)."""
from collections import OrderedDict
from threading import Lock
from time import monotonic
from backend.schemas import AnalysisResult


class EvidenceStore:
    def __init__(self, ttl=8.0, capacity=2048):
        self.ttl, self.capacity = ttl, capacity
        self._items = OrderedDict()
        self._cooldown = OrderedDict()
        self._lock = Lock()

    def record(self, event: AnalysisResult):
        with self._lock:
            key = (event.session_id, event.frame_seq)
            # Repeated sequence numbers cannot replace evidence already issued.
            if key not in self._items:
                self._items[key] = (monotonic(), event.model_dump())
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)

    def trusted(self, event: AnalysisResult, event_id: str | None = None) -> bool:
        with self._lock:
            item = self._items.get((event.session_id, event.frame_seq))
            if item is None or monotonic() - item[0] > self.ttl or item[1] != event.model_dump():
                return False
            # A newer valid image withdraws an older camera hint.
            newer = [value for (sid, seq), value in self._items.items()
                     if sid == event.session_id and seq > event.frame_seq]
            if not newer:
                return True
            latest = max(newer, key=lambda x: x[0])[1]
            if event.deviations:
                current_ids = {d['event_id'] for d in latest['deviations']} if latest['feedback_allowed'] else set()
                return latest['tracking_quality'] == 'good' and (event_id in current_ids if event_id else bool({d.event_id for d in event.deviations} & current_ids))
            return latest['tracking_quality'] == event.tracking_quality and not latest['feedback_allowed']

    def reserve(self, session_id: str, kind: str, seconds=10.0) -> bool:
        with self._lock:
            now, key = monotonic(), (session_id, kind)
            if now - self._cooldown.get(key, -float('inf')) < seconds:
                return False
            self._cooldown[key] = now
            self._cooldown.move_to_end(key)
            while len(self._cooldown) > self.capacity:
                self._cooldown.popitem(last=False)
            return True


    def correction_spoken(self, session_id, event_id):
        with self._lock:
            return (session_id, 'episode:' + event_id) in self._cooldown

    def claim_correction(self, session_id, event_id, seconds=10.0):
        with self._lock:
            now = monotonic()
            once = (session_id, 'episode:' + event_id)
            clock = (session_id, 'correction')
            if once in self._cooldown or now - self._cooldown.get(clock, -float('inf')) < seconds:
                return False
            self._cooldown[once] = now
            self._cooldown[clock] = now
            self._cooldown.move_to_end(clock)
            while len(self._cooldown) > self.capacity:
                self._cooldown.popitem(last=False)
            return True


store = EvidenceStore()
