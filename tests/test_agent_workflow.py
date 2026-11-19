import json
import pytest
import httpx
from fastapi.testclient import TestClient
from backend import agent, llm, memory
from backend.evidence import EvidenceStore
from backend.main import app
from backend.schemas import AnalysisResult
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
