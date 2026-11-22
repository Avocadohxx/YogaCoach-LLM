import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend import memory
from backend.session_activity import incomplete
from backend.database import connection
client=TestClient(app)

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setenv('YOGACOACH_DB_PATH',str(tmp_path/'priority.db'))
    monkeypatch.delenv('YOGACOACH_ALLOW_TEST_WRITES',raising=False)

def test_no_client_fabricated_memory():
    memory.create_session('s','tadasana')
    assert client.post('/api/memory/sessions/s/events',json={'event':{'type':'invented'}}).status_code==403
    assert client.post('/api/memory/sessions/s/feedback',json={'feedback_text':'invented'}).status_code==403
    assert client.post('/api/memory/sessions/s/analysis',json={'feedback_allowed':True}).status_code==403
    assert memory.get_pose_events('s')==[]

def test_unknown_session_rejected_before_inference(monkeypatch):
    import backend.inference_133 as inference
    monkeypatch.setattr(inference,'infer',lambda _:pytest.fail('must reject before inference'))
    assert client.post('/api/pose/frame?session_id=unknown&frame_seq=0&timestamp_ms=0',content=b'bad',headers={'Content-Type':'image/jpeg'}).status_code==409

def test_interruption_does_not_invent_finish_or_summary():
    memory.create_session('s','tadasana')
    assert client.post('/api/memory/sessions/s/heartbeat',json={}).status_code==200
    with connection() as conn:conn.execute('UPDATE session_activity SET last_seen=0')
    row=incomplete()[0]
    assert row['state']=='interrupted' and row['ended_at'] is None and row['summary'] is None
    assert client.post('/api/memory/sessions/s/heartbeat',json={}).status_code==200
    assert incomplete()[0]['state']=='active'

def test_readiness_rejects_lfs_pointer(tmp_path,monkeypatch):
    path=tmp_path/'model.onnx';path.write_text('version https://git-lfs.github.com/spec/v1\n')
    monkeypatch.setenv('POSE133_MODEL_PATH',str(path))
    result=client.get('/api/ready').json()
    assert result['status']=='not_ready' and result['model']['reason']=='lfs_pointer'
    assert 'path' not in result['model']

def test_new_stream_can_seek_back_without_becoming_permanently_out_of_order():
    from backend.online_rules_133 import OnlineRules
    from tests.test_online_correction_133 import frame_for
    memory.create_session('seek','tadasana')
    service=OnlineRules()
    service.analyze(frame_for('seek',1000),'rtmw_x_384.onnx')
    event=service.analyze(frame_for('seek',1001,timestamp_ms=0,stream_id='after-seek'),'rtmw_x_384.onnx')
    assert 'out_of_order_frame' not in event.reason_codes
    assert not event.feedback_allowed

def test_declared_raised_phase_rejects_obvious_arms_down():
    from backend.online_rules_133 import OnlineRules
    from tests.test_pose_features_133 import skeleton
    from backend.schemas import PoseFrame133
    memory.create_session('phase','tadasana')
    frame=PoseFrame133.model_validate({**skeleton(),'session_id':'phase','pose_id':'tadasana','phase':'arms_up_hold','camera_view':'front','frame_seq':0})
    event=OnlineRules().analyze(frame,'rtmw_x_384.onnx')
    assert 'phase_mismatch_arms_down' in event.reason_codes and not event.feedback_allowed

def test_rule_cache_invalidates_on_file_change(tmp_path,monkeypatch):
    import json
    from pathlib import Path
    from backend.rule_config import active_rules
    path=tmp_path/'rule.json';raw=json.loads((Path(__file__).resolve().parents[1]/'knowledge/tadasana_rules_B.json').read_text())
    path.write_text(json.dumps(raw));monkeypatch.setenv('POSE133_TADASANA_RULES_PATH',str(path))
    first,_=active_rules('tadasana');first['reviewed']=False
    assert active_rules('tadasana')[0]['reviewed']
    raw['version']='cache-new-version';path.write_text(json.dumps(raw))
    assert active_rules('tadasana')[0]['version']=='cache-new-version'

def test_busy_server_has_bounded_admission(monkeypatch):
    import backend.routes_inference as routes
    memory.create_session('busy','tadasana')
    class Busy:
        def acquire(self,blocking=False):return False
    monkeypatch.setattr(routes,'admission',Busy())
    response=client.post('/api/pose/frame?session_id=busy&frame_seq=0&timestamp_ms=0',content=b'image',headers={'Content-Type':'image/jpeg'})
    assert response.status_code==429 and response.headers['retry-after']=='1'

def test_cross_session_focus_uses_only_server_rule_episodes():
    from backend.tools import context_for
    memory.create_session('previous','tadasana')
    memory.save_pose_event('previous',{'type':'elbow_bend','side':'left','rule_version':'r','source_model':'m','server_generated':True})
    memory.finish_session('previous')
    memory.create_session('now','tadasana')
    assert context_for('now','tadasana')['prior_focus']==[{'type':'elbow_bend','side':'left'}]

def test_rule_content_change_resets_pending_even_if_version_unchanged(tmp_path,monkeypatch):
    import json
    from pathlib import Path
    from backend.online_rules_133 import OnlineRules
    from tests.test_online_correction_133 import frame_for
    raw=json.loads((Path(__file__).resolve().parents[1]/'knowledge/tadasana_rules_B.json').read_text())
    path=tmp_path/'rule.json';path.write_text(json.dumps(raw));monkeypatch.setenv('POSE133_TADASANA_RULES_PATH',str(path))
    memory.create_session('changed','tadasana');service=OnlineRules()
    for t in range(0,1201,300):service.analyze(frame_for('changed',t),'rtmw_x_384.onnx')
    raw['rules'][0]['trigger_range'][0]=164.;path.write_text(json.dumps(raw))
    event=service.analyze(frame_for('changed',1500),'rtmw_x_384.onnx')
    assert not event.feedback_allowed
    assert event.rule_evaluation['pending_count']==1
