import json
import pytest
import httpx
from fastapi.testclient import TestClient
from backend import agent, llm, memory
from backend.evidence import EvidenceStore
from backend.main import app
from backend.schemas import AnalysisResult, RuleDeviation
from experiments.detection.synthetic_day1 import make_frame

client = TestClient(app)


@pytest.fixture
def practice(tmp_path, monkeypatch):
    monkeypatch.setenv('YOGACOACH_DB_PATH', str(tmp_path / 'agent.db'))
    snapshots = EvidenceStore()
    monkeypatch.setattr(agent, 'store', snapshots)
    frame = make_frame()
    memory.create_session(frame['session_id'], frame['pose_id'])
    event = client.post('/api/analyze', json=frame).json()
    # A partial observation requests a camera hint, never correction.
    event['tracking_quality'] = 'partial'
    event = AnalysisResult.model_validate(event)
    snapshots.record(event)
    return event, snapshots


def test_graph_calls_tools_and_selects_only_allowlisted_hint(practice, monkeypatch):
    event, _ = practice
    memory.set_user_preference('feedback_length', 'short')
    calls = []
    monkeypatch.setattr(llm, 'select_message', lambda pref: calls.append(pref) or 'short')
    reply = agent.feedback_for(event)
    assert calls == ['short']
    assert reply.should_speak and reply.mode == 'llm'
    assert reply.feedback_type == 'camera_hint'
    assert reply.tools_used == ['analysis_snapshot', 'reference_for', 'context_for']
    assert len(memory.get_recent_feedback(event.session_id)) == 1
    assert agent.feedback_for(event).reason == 'cooldown'
    assert calls == ['short']


@pytest.mark.parametrize('failure', ['timeout', 'invalid'])
def test_provider_failure_uses_template(practice, monkeypatch, failure):
    event, _ = practice
    def select(_):
        if failure == 'timeout':
            raise httpx.ReadTimeout('secret-must-not-be-exposed')
        return 'invented_joint_correction'
    monkeypatch.setattr(llm, 'select_message', select)
    reply = agent.feedback_for(event)
    assert reply.mode == 'template' and reply.should_speak
    assert 'secret' not in reply.model_dump_json()
    assert reply.feedback_type == 'camera_hint'


def test_forged_and_expired_snapshots_do_not_call_provider(practice, monkeypatch):
    event, snapshots = practice
    monkeypatch.setattr(llm, 'select_message', lambda _: pytest.fail('must not call provider'))
    assert agent.feedback_for(event.model_copy(update={'timestamp_ms': 999})).reason == 'untrusted_or_expired'
    snapshots.ttl = -1
    assert agent.feedback_for(event).reason == 'untrusted_or_expired'


def test_new_good_frame_withdraws_slow_hint(practice, monkeypatch):
    event, snapshots = practice
    def select(_):
        snapshots.record(event.model_copy(update={'frame_seq': event.frame_seq + 1, 'tracking_quality': 'good'}))
        return 'full'
    monkeypatch.setattr(llm, 'select_message', select)
    assert agent.feedback_for(event).reason == 'evidence_withdrawn'
    assert memory.get_recent_feedback(event.session_id) == []


def test_finished_session_is_not_used(practice):
    event, _ = practice
    memory.finish_session(event.session_id)
    assert agent.feedback_for(event).reason == 'tools_unavailable'


def test_provider_http_contract(monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'test-only')
    monkeypatch.setenv('LLM_BASE_URL', 'https://provider.invalid/v1')
    monkeypatch.setenv('LLM_MODEL', 'test')
    actual_client = httpx.Client
    def handle(request):
        assert str(request.url) == 'https://provider.invalid/v1/chat/completions'
        payload = json.loads(request.content)
        assert json.loads(payload['messages'][1]['content']) == {'feedback_length': 'short'}
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"message_id":"short"}'}}]})
    monkeypatch.setattr(llm.httpx, 'Client', lambda **kw: actual_client(transport=httpx.MockTransport(handle), **kw))
    assert llm.select_message('short') == 'short'


def test_provider_receives_numeric_rule_summary_and_returns_structured_advice(monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'test-only')
    monkeypatch.setenv('LLM_BASE_URL', 'https://provider.invalid/v1')
    monkeypatch.setenv('LLM_MODEL', 'test')
    actual_client = httpx.Client
    def handle(request):
        payload = json.loads(request.content)
        assert payload['model'] == 'test'
        user = json.loads(payload['messages'][1]['content'])
        assert user['observed_value'] == 151.2
        assert user['reference_range'] == [168.0, 180.0]
        assert user['target'] == 'left_elbow'
        assert 'keypoints' not in user and 'session_id' not in user
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({
            'text': '可以在舒适范围内轻轻伸展左肘。',
            'target': 'left_elbow', 'grounded_event_type': 'elbow_bend',
        }, ensure_ascii=False)}}]})
    monkeypatch.setattr(llm.httpx, 'Client', lambda **kw: actual_client(transport=httpx.MockTransport(handle), **kw))
    result = llm.generate_correction({
        'pose': 'tadasana', 'target': 'left_elbow', 'event_type': 'elbow_bend',
        'feature_name': 'left_elbow_angle_deg', 'observed_value': 151.2, 'unit': 'deg',
        'reference_range': [168.0, 180.0], 'phase': 'arms_up_hold', 'duration_ms': 1800,
        'minimum_keypoint_score': 0.8, 'safety_constraints': ['不要强行伸展'],
    })
    assert result.target == 'left_elbow'
    assert result.grounded_event_type == 'elbow_bend'
    assert '伸展' in result.text


def test_confirmed_correction_sends_numeric_evidence_and_accepts_grounded_llm_reply(practice, monkeypatch):
    event, _ = practice
    selected = {
        'event_id': 'episode-1', 'type': 'elbow_bend', 'target': 'left_elbow',
        'rule_id': 'left_elbow_bend_overhead', 'rule_version': 'tadasana-test-v1', 'feature_name': 'left_elbow_angle_deg',
        'observed_value': 151.2, 'reference_range': [168.0, 180.0],
        'duration_ms': 1800, 'min_keypoint_score': 0.8,
    }
    selected['rule_version'] = 'tadasana-rtmw-draft-v1'
    selected['event_id'] = 'synthetic-day1-episode-1'
    deviation = RuleDeviation(**selected)
    event = event.model_copy(update={
        'analysis_mode': 'reviewed_rules_133', 'reference_status': 'reviewed_rule_config',
        'assessment_status': 'deviation', 'feedback_allowed': True,
        'rule_evaluation': {'phase': 'arms_up_hold'},
        'deviations': [deviation],
    })
    monkeypatch.setattr(agent, 'store', EvidenceStore())
    agent.store.record(event)
    captured = {}
    def generate(evidence):
        captured.update(evidence)
        return llm.CoachingSuggestion(text='可以在舒适范围内轻轻伸展左肘，不必锁死。',
            target='left_elbow', grounded_event_type='elbow_bend')
    monkeypatch.setattr(llm, 'generate_correction', generate)
    result = agent.feedback_for(event)
    assert captured['observed_value'] == 151.2
    assert captured['reference_range'] == [168.0, 180.0]
    assert captured['unit'] == 'deg'
    assert 'session_id' not in captured and 'keypoints' not in captured
    assert result.mode == 'llm' and result.feedback_type == 'correction'
    assert result.target == 'left_elbow'
    assert result.text == '可以在舒适范围内轻轻伸展左肘，不必锁死。'


def test_default_correction_rules_match_online_ruleset(practice, monkeypatch):
    event, _ = practice
    selected = {
        'event_id': 'synthetic-day1-episode-default-rules', 'type': 'elbow_bend',
        'target': 'left_elbow', 'rule_id': 'left_elbow_bend_overhead',
        'rule_version': 'tadasana-rtmw-draft-v1', 'feature_name': 'left_elbow_angle_deg',
        'observed_value': 151.2, 'reference_range': [168.0, 180.0],
        'duration_ms': 1800, 'min_keypoint_score': 0.8,
    }
    deviation = RuleDeviation(**selected)
    event = event.model_copy(update={
        'analysis_mode': 'reviewed_rules_133', 'reference_status': 'reviewed_rule_config',
        'assessment_status': 'deviation', 'feedback_allowed': True,
        'rule_evaluation': {'phase': 'arms_up_hold'}, 'deviations': [deviation],
    })
    monkeypatch.setattr(agent, 'store', EvidenceStore())
    agent.store.record(event)
    from backend.tools import reference_for
    reference = reference_for('tadasana')
    assert reference['rules_file'].endswith('tadasana_rules_B.json')
    payload = agent._correction_evidence(deviation.model_dump(), event, reference)
    assert payload['reference_range'] == [168.0, 180.0]
    assert payload['observed_value'] == 151.2



@pytest.mark.parametrize('target,event_type,text', [
    ('right_elbow', 'elbow_bend', '伸展左肘。'),
    ('left_elbow', 'torso_tilt', '伸展左肘。'),
    ('left_elbow', 'elbow_bend', '必须锁死关节并治疗疼痛。'),
])
def test_invalid_llm_correction_falls_back_to_safe_template(practice, monkeypatch, target, event_type, text):
    event, _ = practice
    selected = {
        'event_id': 'episode-2', 'type': 'elbow_bend', 'target': 'left_elbow',
        'rule_id': 'left_elbow_bend_overhead', 'rule_version': 'tadasana-test-v1', 'feature_name': 'left_elbow_angle_deg',
        'observed_value': 151.2, 'reference_range': [168.0, 180.0],
        'duration_ms': 1800, 'min_keypoint_score': 0.8,
    }
    selected['rule_version'] = 'tadasana-rtmw-draft-v1'
    selected['event_id'] = 'synthetic-day1-episode-2'
    deviation = RuleDeviation(**selected)
    event = event.model_copy(update={
        'analysis_mode': 'reviewed_rules_133', 'reference_status': 'reviewed_rule_config',
        'assessment_status': 'deviation', 'feedback_allowed': True,
        'rule_evaluation': {'phase': 'arms_up_hold'}, 'deviations': [deviation],
    })
    monkeypatch.setattr(agent, 'store', EvidenceStore())
    agent.store.record(event)
    monkeypatch.setattr(llm, 'generate_correction', lambda _: llm.CoachingSuggestion(
        text=text, target=target, grounded_event_type=event_type))
    reply = agent.feedback_for(event)
    assert reply.mode == 'template'
    assert reply.feedback_type == 'correction'
    assert '治疗疼痛' not in reply.text and '必须锁死' not in reply.text


def test_snapshot_store_is_bounded_and_replay_cannot_overwrite(practice):
    event, _ = practice
    snapshots = EvidenceStore(capacity=1)
    snapshots.record(event)
    changed = event.model_copy(update={'timestamp_ms': 999})
    snapshots.record(changed)
    assert not snapshots.trusted(changed)
    assert snapshots.trusted(event)
    snapshots.record(event.model_copy(update={'frame_seq': event.frame_seq + 1}))
    assert not snapshots.trusted(event)


def test_real_http_analysis_is_accepted_by_graph(practice, monkeypatch):
    event, snapshots = practice
    frame = make_frame()
    frame['frame_seq'] += 10
    for point in frame['landmarks']:
        point['visibility'] = 0.6
    import backend.routes_pose as routes
    monkeypatch.setattr(routes, 'store', snapshots)
    monkeypatch.setattr(llm, 'select_message', lambda _: 'full')
    analysis = client.post('/api/analyze', json=frame)
    assert analysis.status_code == 200
    reply = client.post('/api/agent/feedback', json=analysis.json())
    assert reply.status_code == 200
    assert reply.json()['mode'] == 'llm'
    assert reply.json()['feedback_type'] == 'camera_hint'
    assert reply.json()['should_speak'] is True


def test_synthetic_event_never_calls_tools_or_provider(monkeypatch):
    from experiments.detection.synthetic_day1 import make_mocks
    sample = next(e for e in make_mocks().values() if e['deviations'])
    monkeypatch.setattr(agent, 'reference_for', lambda _: pytest.fail('synthetic blocked before tools'))
    result = client.post('/api/agent/feedback', json=sample)
    assert result.status_code == 200
    assert result.json()['reason'] == 'synthetic_event'
