"""Side-bend online integration using synthetic keypoints and isolated DBs."""
import json
import math
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend import agent, llm, memory
from backend.evidence import EvidenceStore
from backend.main import app
from backend.online_rules_133 import OnlineRules
from backend.rule_config import active_rules
import backend.routes_inference as routes
from tests.test_online_correction_133 import raw

client = TestClient(app)


def points(*, single=False, bent=True, tilt=25):
    data = raw(bent)
    if single:
        data['keypoints'][8] = [40., 45.]
        data['keypoints'][10] = [40., 60.]
    angle = math.radians(tilt)
    for i in range(5, 13):
        x, y = data['keypoints'][i]
        x, y = x - 50, y - 60
        data['keypoints'][i] = [50 + x * math.cos(angle) - y * math.sin(angle),
                                60 + x * math.sin(angle) + y * math.cos(angle)]
    return data


@pytest.fixture
def side_practice(tmp_path, monkeypatch):
    monkeypatch.setenv('YOGACOACH_DB_PATH', str(tmp_path / 'side.db'))
    sid = uuid4().hex
    memory.create_session(sid, 'ardhakati_chakrasana')
    snapshots, service = EvidenceStore(), OnlineRules()
    monkeypatch.setattr(routes, 'store', snapshots)
    monkeypatch.setattr(agent, 'store', snapshots)
    monkeypatch.setattr(routes, 'online_rules', service)
    monkeypatch.setattr(routes.inference_133, 'source_model', lambda: 'rtmw_x_384.onnx')
    return sid


def frames(sid, monkeypatch, *, single=False, bent=True, tilt=25,
           direction='image_right', phase='side_bend_hold', start=0, end=1500):
    data = points(single=single, bent=bent, tilt=tilt)
    monkeypatch.setattr(routes.inference_133, 'infer', lambda _: (data['keypoints'], data['scores']))
    jpeg = cv2.imencode('.jpg', np.zeros((120, 120, 3), dtype=np.uint8))[1].tobytes()
    for timestamp in range(start, end + 1, 300):
        response = client.post('/api/pose/frame', content=jpeg,
            headers={'content-type': 'image/jpeg'}, params=dict(
                session_id=sid, pose_id='ardhakati_chakrasana', frame_seq=timestamp,
                timestamp_ms=timestamp, phase=phase, camera_view='front',
                movement_variant='single_arm_overhead' if single else 'both_arms_overhead',
                raised_arm_side='left' if single else 'unknown', bend_direction=direction))
        assert response.status_code == 200, response.text
    return response.json()['analysis']


def test_default_online_side_config_is_demo_enabled_without_claiming_professional_review():
    rules, _ = active_rules('ardhakati_chakrasana')
    assert rules['reviewed']
    assert rules['review_record']['professional_review_completed'] is False
    assert rules['version'] == 'ardhakati-rtmw-demo-v2'
    draft = json.loads((Path(__file__).resolve().parents[1] / 'knowledge/ardhakati_chakrasana_rules.json').read_text())
    assert not draft['reviewed']
    ready = client.get('/api/ready').json()['rules']['ardhakati_chakrasana']
    assert ready['correction_phases'] == ['arms_up_hold', 'side_bend_hold']


@pytest.mark.parametrize('single,phase', [(False, 'side_bend_hold'),
                                       (True, 'side_bend_hold'), (True, 'arms_up_hold')])
def test_image_endpoint_confirms_applicable_elbow_and_calls_llm(side_practice, monkeypatch, single, phase):
    captured = []
    def generate(evidence):
        captured.append(evidence)
        return llm.CoachingSuggestion(text='在舒适范围内轻轻伸展左肘，不必锁死。',
                                      target='left_elbow', grounded_event_type='elbow_bend')
    monkeypatch.setattr(llm, 'generate_correction', generate)
    pending = frames(side_practice, monkeypatch, single=single, phase=phase, end=1200)
    assert not pending['feedback_allowed']
    event = frames(side_practice, monkeypatch, single=single, phase=phase, start=1500)
    assert event['feedback_allowed'] and event['analysis_mode'] == 'reviewed_rules_133'
    assert [d['target'] for d in event['deviations']] == ['left_elbow']
    assert event['rule_evaluation']['assessment_coverage']['complete_for_enabled_phase_rules']
    reply = client.post('/api/agent/feedback', json=event).json()
    assert reply['mode'] == 'llm' and reply['should_speak']
    assert captured[0]['confirmed_deviation']['movement_variant'] == ('single_arm_overhead' if single else 'both_arms_overhead')
    assert captured[0]['rule_provenance']['review_record']['professional_review_completed'] is False
    assert not client.post('/api/agent/feedback', json=event).json()['should_speak']
    assert len(captured) == 1
    assert len(memory.get_pose_events(side_practice)) == 1


def test_wrong_image_direction_reaches_llm_and_history_with_transformed_value(side_practice, monkeypatch):
    captured = []
    def generate(evidence):
        captured.append(evidence)
        return llm.CoachingSuggestion(text='请先回正，再核对计划倾斜的画面方向。',
                                      target='torso', grounded_event_type='bend_direction_mismatch')
    monkeypatch.setattr(llm, 'generate_correction', generate)
    event = frames(side_practice, monkeypatch, bent=False, direction='image_left')
    assert [d['type'] for d in event['deviations']] == ['bend_direction_mismatch']
    reply = client.post('/api/agent/feedback', json=event).json()
    assert reply['mode'] == 'llm' and reply['target'] == 'torso'
    evidence = captured[0]['confirmed_deviation']
    assert evidence['observed_value'] == pytest.approx(25)
    assert evidence['comparison_value'] == pytest.approx(-25)
    assert evidence['bend_direction'] == 'image_left'
    assert evidence['reference_range'] == [5.0, None]
    # No model summary call: finish as a DB fact, then inspect numeric evidence.
    memory.finish_session(side_practice)
    snapshot = memory.get_progress_snapshot(pose_id='ardhakati_chakrasana')
    measurement = snapshot['sessions'][0]['confirmed_measurements'][0]
    assert measurement['comparison_value'] == -25
    assert measurement['deviation_from_range'] == 30


def test_unknown_direction_explains_missing_context_instead_of_calling_llm(side_practice, monkeypatch):
    monkeypatch.setattr(llm, 'generate_correction', lambda _: pytest.fail('missing direction'))
    event = frames(side_practice, monkeypatch, direction='unknown')
    assert not event['feedback_allowed']
    assert 'independent_intended_direction_required' in event['reason_codes']


def test_return_and_side_switch_interrupt_old_episode(side_practice, monkeypatch):
    event = frames(side_practice, monkeypatch)
    assert event['feedback_allowed']
    event = frames(side_practice, monkeypatch, phase='return_upright', start=1800, end=1800)
    assert not event['feedback_allowed']
    assert memory.get_pose_events(side_practice)[0]['payload']['lifecycle_status'] == 'interrupted'
    changed = frames(side_practice, monkeypatch, direction='image_left', start=2100, end=2100)
    assert not changed['feedback_allowed']
