import json
from pathlib import Path
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend import inference_133

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]


def frame():
    path = ROOT / 'data/reference/tadasana_rtmw_original_correct_full/keypoints_133.jsonl'
    data = json.loads(path.open().readline())
    return {**data, 'session_id': 'test133', 'pose_id': 'tadasana', 'frame_seq': 0,
            'layout': 'COCO-WholeBody 133', 'coordinate_space': 'image_pixels', 'phase': 'hold', 'camera_view': 'front'}


def test_133_scores_and_pixel_coordinates_keep_their_semantics():
    data = frame()
    data['scores'] = [1.075] * 133
    response = client.post('/api/analyze', json=data)
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result['observations']) == 8
    shoulder = next(o for o in result['observations'] if o['name'] == 'shoulder_height_diff_px')
    assert shoulder['value'] == pytest.approx(abs(data['keypoints'][5][1]-data['keypoints'][6][1]))
    assert not result['feedback_allowed']


@pytest.mark.parametrize('change', [{'keypoints': [[0.,0.]] * 33}, {'scores': [1.] * 33}, {'coordinate_space': 'normalized_image'}])
def test_mixed_layout_is_rejected(change):
    assert client.post('/api/analyze', json={**frame(), **change}).status_code == 422


def test_jpeg_endpoint_runs_133_adapter(monkeypatch):
    data = frame()
    monkeypatch.setattr(inference_133, 'infer', lambda image: (data['keypoints'], data['scores']))
    image = cv2.imencode('.jpg', np.zeros((480,640,3), dtype=np.uint8))[1].tobytes()
    result = client.post('/api/pose/frame?session_id=test133&pose_id=tadasana&frame_seq=3&timestamp_ms=50&camera_view=front',content=image,headers={'Content-Type':'image/jpeg'})
    assert result.status_code == 200, result.text
    assert result.json()['layout'] == 'COCO-WholeBody 133'
    assert len(result.json()['keypoints']) == 133
    assert result.json()['analysis']['frame_seq'] == 3


@pytest.mark.parametrize('body,content_type,code', [(b'', 'image/jpeg',422),(b'bad', 'image/jpeg',422),(b'bad','video/mp4',415),(b'x'*(2*1024*1024+1),'image/jpeg',413)])
def test_invalid_media(body,content_type,code):
    response=client.post('/api/pose/frame?session_id=s&frame_seq=0&timestamp_ms=0',content=body,headers={'Content-Type':content_type})
    assert response.status_code == code


@pytest.fixture(autouse=True)
def isolated_active_sessions(tmp_path,monkeypatch):
    from backend import memory
    monkeypatch.setenv('YOGACOACH_DB_PATH',str(tmp_path/'image-api.db'))
    memory.create_session('s','tadasana')
    memory.create_session('test133','tadasana')
