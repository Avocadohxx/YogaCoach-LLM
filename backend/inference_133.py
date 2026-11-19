"""Local RTMW CPU inference, fixed full-image single-person ROI like A's data."""
import os
from pathlib import Path
from threading import Lock
import numpy as np

_lock = Lock()
_model = None
_model_name = None


def infer(image):
    global _model, _model_name
    with _lock:
        if _model is None:
            path = Path(os.getenv('POSE133_MODEL_PATH', str(Path(__file__).resolve().parents[1] / 'data/models/rtmw_x_384.onnx')))
            if not path.is_absolute():
                path = Path(__file__).resolve().parents[1] / path
            if not path.is_file():
                raise RuntimeError('133 点 ONNX 模型未找到，请配置 POSE133_MODEL_PATH。')
            from rtmlib import RTMPose
            _model = RTMPose(onnx_model=str(path), model_input_size=(288, 384), to_openpose=False, backend='onnxruntime', device='cpu')
            _model_name = path.name
        points, scores = _model(image)
    if points.shape != (1, 133, 2) or scores.shape != (1, 133) or not np.isfinite(points).all() or not np.isfinite(scores).all():
        raise RuntimeError('模型输出不是有效 COCO-WholeBody 133 点。')
    return points[0].tolist(), scores[0].tolist()


def source_model():
    return _model_name or 'unavailable'
