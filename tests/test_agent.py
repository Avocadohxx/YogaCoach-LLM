"""Real HTTP regression: measurement and synthetic events cannot cause coaching."""
from fastapi.testclient import TestClient
from backend.main import app
from experiments.detection.synthetic_day1 import make_frame

client = TestClient(app)


def test_measurements_feedback_endpoint_is_available():
    response = client.post('/api/analyze', json=make_frame())
    assert response.status_code == 200
    reply = client.post('/api/agent/feedback', json=response.json())
    assert reply.status_code == 200
    assert reply.json()['should_speak'] is False
    assert reply.json()['feedback_type'] == 'none'


def test_forged_measurement_cannot_enable_correction():
    event = client.post('/api/analyze', json=make_frame()).json()
    event['feedback_allowed'] = True
    assert client.post('/api/agent/feedback', json=event).status_code == 422


def test_missing_frame_contract_is_rejected():
    frame = make_frame()
    del frame['phase']
    assert client.post('/api/analyze', json=frame).status_code == 422


def test_measurement_session_finishes_without_invented_deviations(tmp_path, monkeypatch):
    monkeypatch.setenv('YOGACOACH_DB_PATH', str(tmp_path / 'practice.db'))
    frame = make_frame()
    session_id = frame['session_id']
    assert client.post('/api/memory/sessions', json={
        'session_id': session_id, 'pose_id': frame['pose_id'],
        'started_at': '2026-11-19T12:00:00Z',
    }).status_code == 200
    event = client.post('/api/analyze', json=frame).json()
    stored = client.post(f'/api/memory/sessions/{session_id}/analysis', json=event)
    assert stored.status_code == 403  # production records are server-owned
    finished = client.post(f'/api/memory/sessions/{session_id}/finish', json={
        'ended_at': '2026-11-19T12:01:00Z',
    })
    assert finished.status_code == 200
    assert client.get(f'/api/memory/sessions/{session_id}/events').json()['items'] == []
    assert client.get('/api/memory/sessions').json()['items'][0]['ended_at'] is not None
