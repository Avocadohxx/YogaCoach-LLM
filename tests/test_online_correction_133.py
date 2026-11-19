"""Deterministic geometry tests; not real-person accuracy/clinical validation."""
from copy import deepcopy
import json
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
from backend.schemas import PoseFrame133
import backend.routes_inference as routes
from tests.test_pose_features_133 import skeleton

client = TestClient(app)


def raw(bent=True):
    frame = skeleton()
    frame['keypoints'][7] = [60.,15.]
    frame['keypoints'][9] = [75.,15.] if bent else [60.,0.]
    frame['keypoints'][8] = [40.,15.]
    frame['keypoints'][10] = [40.,0.]
    return frame


@pytest.fixture
def practice(tmp_path, monkeypatch):
    monkeypatch.setenv('YOGACOACH_DB_PATH', str(tmp_path/'online.db'))
    sid = uuid4().hex
    memory.create_session(sid, 'tadasana')
    snapshots, service = EvidenceStore(), OnlineRules()
    monkeypatch.setattr(routes, 'store', snapshots)
    monkeypatch.setattr(agent, 'store', snapshots)
    monkeypatch.setattr(routes, 'online_rules', service)
    monkeypatch.setattr(routes.inference_133, 'source_model', lambda: 'rtmw_x_384.onnx')
    monkeypatch.setattr(llm, 'select_correction', lambda _: 'short')
    return sid, snapshots, service


def frame_for(sid,t,bent=True,**changes):
    data=raw(bent)
    data.update(session_id=sid,pose_id='tadasana',frame_seq=t,timestamp_ms=t,phase='arms_up_hold',camera_view='front')
    data.update(changes)
    return PoseFrame133.model_validate(data)


def sequence(practice, start=0, end=1500, **changes):
    sid, snapshots, service = practice
    for t in range(start,end+1,300):
        event=service.analyze(frame_for(sid,t,**changes),'rtmw_x_384.onnx')
        snapshots.record(event)
    return event


def test_confirmation_grounding_dedup_and_persistence(practice):
    sid, snapshots, service=practice
    pending=sequence(practice,end=1200)
    assert not pending.feedback_allowed
    assert memory.get_pose_events(sid)==[]
    event=sequence(practice,start=1500,end=1500)
    assert event.analysis_mode=='reviewed_rules_133'
    assert event.feedback_allowed and len(event.deviations)==1
    assert event.deviations[0].confidence is None
    assert event.deviations[0].duration_ms==1500
    first=client.post('/api/agent/feedback',json=event.model_dump()).json()
    assert first['should_speak'] and first['feedback_type']=='correction'
    assert first['target']=='left_elbow' and first['grounded_event_type']=='elbow_bend'
    assert '左' in first['text']
    repeated=sequence(practice,start=1800,end=2100)
    second=client.post('/api/agent/feedback',json=repeated.model_dump()).json()
    assert not second['should_speak']
    assert len(memory.get_pose_events(sid))==1
    assert len(memory.get_recent_feedback(sid))==1
    assert '持续肘部弯曲' in memory.finish_session(sid)


@pytest.mark.parametrize('change',[{'phase':'prepare'},{'phase':'hold'},{'phase':'arms_down_hold'}, {'camera_view':'side'},{'scores':[.1]*133}])
def test_unsupported_context_never_corrects(practice,change):
    event=sequence(practice,**change)
    assert not event.feedback_allowed
    assert not event.deviations


def test_gaps_and_new_stream_reset_confirmation(practice):
    assert not sequence(practice,end=1200).feedback_allowed
    assert not sequence(practice,start=1500,end=1500,stream_id='after-seek').feedback_allowed
    assert not sequence(practice,start=2400,end=2400,stream_id='after-seek').feedback_allowed


def test_session_isolation_and_out_of_order(practice):
    sid,_,service=practice
    sequence(practice,end=1200)
    other=uuid4().hex;memory.create_session(other,'tadasana')
    assert not service.analyze(frame_for(other,1500),'rtmw_x_384.onnx').feedback_allowed
    old=service.analyze(frame_for(sid,900),'rtmw_x_384.onnx')
    assert 'out_of_order_frame' in old.reason_codes
    assert sequence(practice,start=1500,end=1500).feedback_allowed


def test_recovery_withdraws_old_reply_and_keeps_episode_lifecycle(practice):
    sid, snapshots, service=practice
    original=sequence(practice)
    for t in range(1800,2701,300):
        cleared=service.analyze(frame_for(sid,t,bent=False),'rtmw_x_384.onnx');snapshots.record(cleared)
    reply=client.post('/api/agent/feedback',json=original.model_dump()).json()
    assert not reply['should_speak']
    episode=memory.get_pose_events(sid)[0]
    assert episode['payload']['lifecycle_status']=='recovered'
    assert memory.get_recent_feedback(sid)==[]


def test_low_quality_interrupts_without_reporting_recovery(practice):
    sid,_,_=practice
    sequence(practice)
    event=sequence(practice,start=1800,end=1800,scores=[.1]*133)
    assert not event.feedback_allowed
    assert memory.get_pose_events(sid)[0]['payload']['lifecycle_status']=='interrupted'
    assert not sequence(practice,start=2100,end=3300).feedback_allowed


def test_unreviewed_side_bend_stays_guarded(practice):
    sid, snapshots, service=practice
    side=uuid4().hex;memory.create_session(side,'ardhakati_chakrasana')
    for t in range(0,1801,300):
        event=service.analyze(frame_for(side,t,pose_id='ardhakati_chakrasana',phase='side_bend_hold',movement_variant='both_arms_overhead',bend_direction='image_left'),'rtmw_x_384.onnx')
    assert 'rules_require_manual_review' in event.reason_codes
    assert not event.feedback_allowed
    assert memory.get_pose_events(side)==[]


def test_jpeg_route_to_feedback_with_server_model_provenance(practice, monkeypatch):
    sid,_,_=practice
    data=raw()
    monkeypatch.setattr(routes.inference_133,'infer',lambda image:(data['keypoints'],data['scores']))
    jpeg=cv2.imencode('.jpg',np.zeros((120,120,3),dtype=np.uint8))[1].tobytes()
    for t in range(0,1501,300):
        response=client.post(f'/api/pose/frame?session_id={sid}&pose_id=tadasana&phase=arms_up_hold&camera_view=front&frame_seq={t}&timestamp_ms={t}',content=jpeg,headers={'content-type':'image/jpeg'})
        assert response.status_code==200,response.text
    event=response.json()['analysis']
    assert event['feedback_allowed']
    assert client.post('/api/agent/feedback',json=event).json()['feedback_type']=='correction'
    forged=deepcopy(event);forged['deviations'][0]['observed_value']=1.
    assert not client.post('/api/agent/feedback',json=forged).json()['should_speak']


def test_direct_keypoints_cannot_self_authorize_correction(practice):
    sid,_,_=practice
    result=client.post('/api/analyze',json=frame_for(sid,0).model_dump())
    assert result.status_code==200
    assert result.json()['analysis_mode']=='measurements_only'
    assert not result.json()['feedback_allowed']


def test_changing_context_interrupts_confirmed_episode(practice):
    sid,_,_=practice
    sequence(practice)
    next_event=sequence(practice,start=1800,end=1800,stream_id='different-video')
    assert not next_event.feedback_allowed
    assert memory.get_pose_events(sid)[0]['payload']['lifecycle_status']=='interrupted'


def test_wrong_model_cannot_activate_rules(practice):
    sid,_,service=practice
    for t in range(0,1501,300):
        event=service.analyze(frame_for(sid,t),'dwpose_l_384.onnx')
    assert not event.feedback_allowed
    assert 'source_model_missing_or_mismatch' in event.reason_codes


def test_out_of_frame_required_joints_block_correction(practice):
    event=sequence(practice,image_width=50,image_height=120)
    assert not event.feedback_allowed
    assert 'required_landmark_out_of_frame' in event.reason_codes


def test_claim_correction_is_atomic_and_once_per_episode():
    from concurrent.futures import ThreadPoolExecutor
    store=EvidenceStore()
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims=list(pool.map(lambda _:store.claim_correction('s','event-1'),range(16)))
    assert sum(claims)==1
    assert not store.claim_correction('s','event-2')


def test_selected_event_must_still_be_current_even_when_another_event_remains(practice, monkeypatch):
    sid,snapshots,service=practice
    event=sequence(practice)
    def slow_selection(_):
        newer=event.model_copy(deep=True)
        newer.frame_seq+=1
        newer.deviations[0].event_id='some-other-current-event'
        snapshots.record(newer)
        return 'short'
    monkeypatch.setattr(llm,'select_correction',slow_selection)
    assert not client.post('/api/agent/feedback',json=event.model_dump()).json()['should_speak']
    assert memory.get_recent_feedback(sid)==[]


def test_correction_provider_failure_falls_back_to_grounded_template(practice,monkeypatch):
    event=sequence(practice)
    def fail(_):
        raise ValueError('provider failure')
    monkeypatch.setattr(llm,'select_correction',fail)
    reply=client.post('/api/agent/feedback',json=event.model_dump()).json()
    assert reply['should_speak'] and reply['mode']=='template'
    assert reply['target']=='left_elbow'
    assert '左' in reply['text']


def test_side_bend_adapter_can_use_independently_reviewed_config(practice,tmp_path,monkeypatch):
    # Test fixture approval is local to this test, never written into project rules.
    rules=json.loads((Path(__file__).resolve().parents[1]/'knowledge/ardhakati_chakrasana_rules.json').read_text())
    rules.update(reviewed=True,review_record={'reviewer':'test-only','scope':'synthetic fixture'})
    path=tmp_path/'rules.json';path.write_text(json.dumps(rules))
    monkeypatch.setenv('POSE133_ARDHAKATI_RULES_PATH',str(path))
    sid=uuid4().hex;memory.create_session(sid,'ardhakati_chakrasana')
    _,_,service=practice
    for t in range(0,1501,300):
        event=service.analyze(frame_for(sid,t,pose_id='ardhakati_chakrasana',phase='side_bend_hold',movement_variant='both_arms_overhead',bend_direction='image_left'),'rtmw_x_384.onnx')
    assert event.feedback_allowed and event.deviations[0].type=='elbow_bend'


def test_slow_inference_frame_cannot_trigger_correction(practice,monkeypatch):
    sid,_,_=practice
    data=raw()
    monkeypatch.setattr(routes.inference_133,'infer',lambda image:(data['keypoints'],data['scores']))
    monkeypatch.setattr(routes,'monotonic',lambda:5.)
    jpeg=cv2.imencode('.jpg',np.zeros((120,120,3),dtype=np.uint8))[1].tobytes()
    result=routes.process(jpeg,sid,'tadasana',0,0,'arms_up_hold','front',received_at=0.)
    assert not result['analysis']['feedback_allowed']
    assert 'inference_frame_expired' in result['analysis']['reason_codes']
