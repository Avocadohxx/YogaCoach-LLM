"""JPEG camera/video frames -> local 133-point inference -> measurements."""
from typing import Literal
from time import monotonic
import logging
import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from backend import inference_133, memory
from backend.load_control import admission
from backend.evidence import store
from backend.online_rules_133 import online_rules
from backend.pose_analyzer_133 import analyze_frame_133
from backend.schemas import PoseFrame133, PoseId

router = APIRouter()
logger = logging.getLogger(__name__)
MAX_BYTES = 2 * 1024 * 1024


def process(data, session_id, pose_id, frame_seq, timestamp_ms, phase, camera_view, stream_id='default', movement_variant='unknown', raised_arm_side='unknown', bend_direction='unknown', received_at=None):
    if not data or not session_id.strip():
        raise HTTPException(422, '图像与会话标识不能为空。')
    try:
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as exc:
        raise HTTPException(422, '无法解码图像。') from exc
    if image is None or max(image.shape[:2]) > 4096:
        raise HTTPException(422, '无法解码图像或尺寸超过 4096。')
    try:
        points, scores = inference_133.infer(image)
    except (ImportError, RuntimeError) as exc:
        logger.exception('133 点模型推理初始化或执行失败。')
        raise HTTPException(503, '133 点推理不可用，请检查模型与推理依赖。') from exc
    frame = PoseFrame133(session_id=session_id, pose_id=pose_id, frame_seq=frame_seq,
        timestamp_ms=timestamp_ms, phase=phase, camera_view=camera_view, keypoints=points, scores=scores, image_width=image.shape[1], image_height=image.shape[0], stream_id=stream_id, movement_variant=movement_variant, raised_arm_side=raised_arm_side, bend_direction=bend_direction)
    # Sequential client requests can take longer than two seconds on CPU.
    # Preserve ordered observations; OnlineRules enforces timestamp/gap limits.
    event = online_rules.analyze(frame, inference_133.source_model())
    store.record(event)
    return {'layout': 'COCO-WholeBody 133', 'coordinate_space': 'image_pixels',
            'image_width': image.shape[1], 'image_height': image.shape[0],
            'keypoints': points, 'scores': scores, 'analysis': event.model_dump(),
            'roi_mode': 'fixed_full_image_single_person_no_detector'}


@router.post('/api/pose/frame', tags=['pose-133'])
async def infer_frame(request: Request, session_id: str = Query(min_length=1, max_length=128),
    pose_id: PoseId = 'tadasana', frame_seq: int = Query(ge=0), timestamp_ms: int = Query(ge=0),
    phase: Literal['prepare', 'hold', 'transition', 'arms_down_hold', 'arms_up_hold', 'side_bend_hold', 'return_upright'] = 'prepare', camera_view: Literal['front', 'side', 'back', 'unknown'] = 'unknown', stream_id: str = Query(default='default', min_length=1, max_length=128),
    movement_variant: Literal['unknown', 'both_arms_overhead', 'single_arm_overhead'] = 'unknown',
    raised_arm_side: Literal['unknown', 'left', 'right'] = 'unknown',
    bend_direction: Literal['unknown', 'image_left', 'image_right'] = 'unknown'):
    received_at = monotonic()
    if movement_variant == 'both_arms_overhead' and raised_arm_side != 'unknown':
        raise HTTPException(422, '双臂举起不能指定单侧举臂。')
    if request.headers.get('content-type', '').split(';')[0] != 'image/jpeg':
        raise HTTPException(415, '请提交 image/jpeg 图像帧。')
    session = memory.get_session(session_id)
    if session is None or session['ended_at'] is not None or session['pose_id'] != pose_id:
        raise HTTPException(409, '请先创建对应动作的有效练习会话。')
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise HTTPException(413, '图像帧超过 2MB。')
    if not admission.acquire(blocking=False):
        raise HTTPException(429, '分析服务忙，请稍后重试。', headers={'Retry-After':'1'})
    try:
        return await run_in_threadpool(process, bytes(data), session_id, pose_id, frame_seq, timestamp_ms, phase, camera_view, stream_id, movement_variant, raised_arm_side, bend_direction, received_at)

    finally:
        admission.release()
