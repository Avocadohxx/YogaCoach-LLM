"""Ordered per-session 133-point rules. Only server image inference enables it."""
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from threading import RLock
from time import monotonic
import os

from backend import memory
from backend.pose_analyzer_133 import analyze_frame_133
from backend.pose_features_133 import extract_features_133
from backend.pose_rules_tadasana import compare_tadasana_frame, load_rules as load_tadasana
from backend.pose_rules_ardhakati import compare_ardhakati_frame, load_rules as load_ardhakati
from backend.tadasana_event_tracker import TadasanaEventTracker
from backend.ardhakati_event_tracker import ArdhakatiEventTracker
from backend.schemas import RuleDeviation

ROOT = Path(__file__).resolve().parents[1]


class OnlineRules:
    def __init__(self, capacity=128, ttl=120):
        self.capacity, self.ttl = capacity, ttl
        self._sessions = OrderedDict()
        self._lock = RLock()

    def reset(self, session_id):
        with self._lock:
            previous = self._sessions.pop(session_id, None)
            if previous and 'comparison' in previous:
                self._interrupt(session_id, previous, previous['timestamp'] + 1)

    def _interrupt(self, sid, previous, timestamp):
        comparison = deepcopy(previous['comparison'])
        comparison['timestamp_ms'] = timestamp
        for rule in comparison['rule_results']:
            rule.update(status='not_applicable', reason='stream_context_changed')
        stopped = previous['tracker'].update(comparison)
        for item in stopped['new_events']:
            if item['status'] == 'interrupted':
                memory.update_rule_episode(sid, item)

    def analyze(self, frame, source_model):
        event = analyze_frame_133(frame)
        with self._lock:
            now = monotonic()
            for sid in list(self._sessions):
                if now - self._sessions[sid]['seen'] > self.ttl:
                    expired = self._sessions.pop(sid)
                    if 'comparison' in expired:
                        self._interrupt(sid, expired, expired['timestamp'] + 1)
            session = memory.get_session(frame.session_id)
            if session is None or session['ended_at'] is not None or session['pose_id'] != frame.pose_id:
                event.reason_codes.append('active_matching_session_required')
                self.reset(frame.session_id)
                return event
            config_path = os.getenv('POSE133_TADASANA_RULES_PATH', str(ROOT / 'knowledge/tadasana_rules_B.json')) if frame.pose_id == 'tadasana' else os.getenv('POSE133_ARDHAKATI_RULES_PATH', str(ROOT / 'knowledge/ardhakati_chakrasana_rules.json'))
            try:
                rules = (load_tadasana if frame.pose_id == 'tadasana' else load_ardhakati)(config_path)
            except (OSError, ValueError):
                event.reason_codes.append('rules_unavailable')
                self.reset(frame.session_id)
                return event
            previous = self._sessions.get(frame.session_id)
            if previous and (frame.frame_seq <= previous['seq'] or frame.timestamp_ms <= previous['timestamp']):
                event.reason_codes.append('out_of_order_frame')
                return event
            max_gap = min((r['temporal']['max_gap_ms'] for r in rules['rules'] if r['enabled'] and r['mode']=='candidate'), default=500)
            if previous and frame.timestamp_ms - previous['timestamp'] > max_gap:
                event.reason_codes.append('frame_gap_reset')
            context = (frame.pose_id, frame.stream_id, frame.phase, frame.movement_variant, frame.raised_arm_side, frame.bend_direction, source_model)
            if previous is None or previous['context'] != context:
                if previous and 'comparison' in previous:
                    self._interrupt(frame.session_id, previous, frame.timestamp_ms)
                previous = dict(tracker=TadasanaEventTracker() if frame.pose_id == 'tadasana' else ArdhakatiEventTracker(), context=context)
            previous.update(seq=frame.frame_seq, timestamp=frame.timestamp_ms, seen=now)
            self._sessions[frame.session_id] = previous
            self._sessions.move_to_end(frame.session_id)
            while len(self._sessions) > self.capacity:
                evicted_sid, evicted = self._sessions.popitem(last=False)
                if 'comparison' in evicted:
                    self._interrupt(evicted_sid, evicted, evicted['timestamp'] + 1)
            features = extract_features_133(frame.model_dump())
            args = dict(phase=frame.phase if frame.phase != 'hold' else 'unknown', camera_view=frame.camera_view,
                        source_model=source_model, phase_source='user_declared', ruleset=rules)
            if frame.pose_id == 'tadasana':
                # Initial online scope is the explicitly selected raised-arm variant.
                if frame.phase != 'arms_up_hold':
                    args['phase'] = 'unknown'
                comparison = compare_tadasana_frame(features, **args)
            else:
                comparison = compare_ardhakati_frame(features, **args, movement_variant=frame.movement_variant,
                    raised_arm_side=frame.raised_arm_side, bend_direction=frame.bend_direction)
            # Any incomplete frame interrupts the WHOLE online correction stream.
            # This avoids confirming a timer while required evidence was missing.
            if event.tracking_quality != 'good':
                for rule in comparison['rule_results']:
                    rule.update(status='not_assessable', reason='tracking_quality_not_good')
            tracked = previous['tracker'].update(comparison)
            previous['comparison'] = deepcopy(comparison)
            for lifecycle in tracked['new_events']:
                if lifecycle['status'] in {'recovered', 'interrupted'}:
                    memory.update_rule_episode(frame.session_id, lifecycle)
            summary = dict(rule_version=rules['version'], reviewed=rules['reviewed'],
                review_record=rules['review_record'], phase=frame.phase, stream_id=frame.stream_id,
                source_model=source_model, assessment_coverage=comparison['assessment_coverage'],
                rule_results=comparison['rule_results'], new_events=tracked['new_events'],
                pending_count=len(tracked['pending_events']), scope='enabled_phase_rules_only_not_full_posture')
            event.rule_evaluation = summary
            if not rules['reviewed']:
                event.reason_codes.append('rules_require_manual_review')
                return event
            if event.tracking_quality != 'good':
                return event
            if comparison['reason_codes'] or not comparison['assessment_coverage']['complete_for_enabled_phase_rules']:
                event.reason_codes += comparison['reason_codes'] or sorted({r['reason'] for r in comparison['rule_results'] if r['status']=='not_assessable' and r['reason']}) or ['explicit_supported_phase_required']
                return event
            event.analysis_mode = 'reviewed_rules_133'
            event.reference_status = 'reviewed_rule_config'
            # Active events remain available if the confirmation response was lost;
            # the Agent deduplicates by event ID, not by frame or posture label.
            active = [e for e in tracked['active_events'] if e['rule_status'] == 'deviation']
            if event.tracking_quality == 'good':
                for item in active:
                    event.deviations.append(RuleDeviation(event_id=item['event_id'], type=item['event_type'],
                        target=item['target'], side='left' if item['target'].startswith('left_') else 'right' if item['target'].startswith('right_') else None,
                        rule_id=item['rule_id'], rule_version=rules['version'], feature_name=item['feature_name'],
                        observed_value=item['observed_value'], reference_range=item['reference_range'],
                        duration_ms=item['duration_ms'], min_keypoint_score=item['min_keypoint_score']))
            event.feedback_allowed = bool(event.deviations)
            if event.deviations:
                event.assessment_status = 'deviation'
            elif comparison['assessment_status'] == 'within_reference':
                event.assessment_status = 'within_reference'
            else:
                event.assessment_status = 'uncalibrated'
                event.reason_codes.append('confirming_sustained_deviation' if tracked['pending_events'] else 'hysteresis_or_incomplete_evidence')
            # Persist confirmed episodes independently of whether a reply is requested.
            for item in tracked['new_events']:
                if item['status'] == 'started' and event.feedback_allowed:
                    dev = next((d for d in event.deviations if d.event_id == item['event_id']), None)
                    if dev:
                        memory.save_pose_event(frame.session_id, {**dev.model_dump(), 'timestamp_ms': frame.timestamp_ms,
                            'start_timestamp_ms': item['start_timestamp_ms'], 'phase': frame.phase, 'source_model': source_model})
            return event


online_rules = OnlineRules()
