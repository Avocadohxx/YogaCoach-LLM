"""Public A→B/B→C draft; requires team review before merging.

Day 1 covers measurements and synthetic fixtures, not calibrated correction.
Agent and memory models remain owned by C/D and are intentionally not defined here.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PoseId = Literal["tadasana", "ardhakati_chakrasana"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class Landmark(ContractModel):
    # Off-image x/y are accepted as input and rejected per feature by the analyzer.
    x: float
    y: float
    z: float
    visibility: float = Field(ge=0.0, le=1.0)


class PoseFrame(ContractModel):
    session_id: str = Field(min_length=1, max_length=128)
    pose_id: PoseId
    frame_seq: int = Field(ge=0)
    timestamp_ms: int = Field(ge=0)
    image_width: int = Field(gt=0, le=16384)
    image_height: int = Field(gt=0, le=16384)
    camera_view: Literal["front", "side", "back", "unknown"]
    coordinate_space: Literal["normalized_image"] = "normalized_image"
    phase: Literal["prepare", "hold"]
    # Anatomical side, NOT the side of the displayed image.
    side: Literal["left", "right"] | None = None
    landmarks: list[Landmark] = Field(min_length=33, max_length=33)

    @model_validator(mode="after")
    def check_pose_side(self):
        if not self.session_id.strip():
            raise ValueError("session_id must not be blank")
        if self.pose_id == "ardhakati_chakrasana" and self.side is None:
            raise ValueError("side is required for ardhakati_chakrasana")
        if self.pose_id == "tadasana" and self.side is not None:
            raise ValueError("side must be null for tadasana")
        return self


class Observation(ContractModel):
    name: str
    value: float | None
    unit: Literal["torso_ratio", "deg", "px", "shoulder_width_ratio"]
    valid: bool
    reason: str | None = None

    @model_validator(mode="after")
    def check_validity(self):
        if self.valid and (self.value is None or self.reason is not None):
            raise ValueError("valid observation needs a value and no reason")
        if not self.valid and (self.value is not None or self.reason is None):
            raise ValueError("invalid observation needs a reason and no value")
        return self


class Deviation(ContractModel):
    # Only used in synthetic mocks on Day 1; no production rule is enabled yet.
    event_id: str
    type: Literal["shoulder_asymmetry", "torso_tilt", "raised_arm_elbow_bend"]
    side: Literal["left_higher", "right_higher", "left", "right"] | None = None
    severity: Literal["mild"]
    confidence: float = Field(ge=0.0, le=1.0)
    duration_ms: int = Field(ge=0)
    feature_name: str
    observed_value: float
    reference_range: list[float] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def ordered_range(self):
        if self.reference_range[0] > self.reference_range[1]:
            raise ValueError("reference_range must be ordered")
        return self


class RuleDeviation(ContractModel):
    event_id: str
    type: Literal['elbow_bend', 'upper_arm_alignment', 'bend_direction_mismatch']
    target: str
    side: Literal['left', 'right'] | None = None
    rule_id: str
    rule_version: str
    feature_name: str
    observed_value: float
    reference_range: list[float | None] = Field(min_length=2, max_length=2)
    duration_ms: int = Field(ge=0)
    min_keypoint_score: float
    # Raw model responses are not calibrated confidence probabilities.
    confidence: None = None
    severity: None = None


class AnalysisResult(ContractModel):
    session_id: str
    pose_id: PoseId
    frame_seq: int = Field(ge=0)
    timestamp_ms: int = Field(ge=0)
    tracking_quality: Literal["good", "partial", "poor"]
    assessment_status: Literal[
        "uncalibrated", "within_reference", "deviation", "not_assessable"
    ]
    analysis_mode: Literal["measurements_only", "synthetic_mock", "reviewed_rules_133"]
    reference_status: Literal["not_loaded", "unvalidated_synthetic", "reviewed_rule_config"]
    feedback_allowed: bool
    observations: list[Observation]
    deviations: list[Deviation | RuleDeviation]
    reason_codes: list[str]
    rule_evaluation: dict | None = None

    @model_validator(mode="after")
    def prevent_unsupported_feedback(self):
        if self.analysis_mode == "measurements_only":
            if self.feedback_allowed or self.deviations:
                raise ValueError("measurements_only cannot issue correction events")
            if self.assessment_status not in ("uncalibrated", "not_assessable"):
                raise ValueError("measurements_only cannot claim calibrated assessment")
            if self.reference_status != "not_loaded":
                raise ValueError("measurement mode has no loaded reference")
        elif self.analysis_mode == 'reviewed_rules_133':
            if self.reference_status != 'reviewed_rule_config' or not self.rule_evaluation:
                raise ValueError('reviewed rules require rule provenance')
            if any(not isinstance(d, RuleDeviation) for d in self.deviations):
                raise ValueError('reviewed rules need rule deviations')
            if self.feedback_allowed and self.tracking_quality != 'good':
                raise ValueError('correction requires good tracking')
        elif self.reference_status != "unvalidated_synthetic":
            raise ValueError("synthetic mocks must be marked unvalidated")
        if self.feedback_allowed and (
            not self.deviations or self.assessment_status != "deviation"
        ):
            raise ValueError("feedback needs a deviation event")
        if self.assessment_status == "not_assessable" and (
            self.feedback_allowed or self.deviations
        ):
            raise ValueError("not_assessable cannot issue correction events")
        return self


class PoseFrame133(ContractModel):
    """COCO-WholeBody pixels and raw model scores; not visibility probabilities."""
    session_id: str = Field(min_length=1, max_length=128)
    pose_id: PoseId
    frame_seq: int = Field(ge=0)
    timestamp_ms: int = Field(ge=0)
    layout: Literal['COCO-WholeBody 133'] = 'COCO-WholeBody 133'
    coordinate_space: Literal['image_pixels'] = 'image_pixels'
    camera_view: Literal['front', 'side', 'back', 'unknown'] = 'unknown'
    phase: Literal['prepare', 'hold', 'transition', 'arms_down_hold', 'arms_up_hold', 'side_bend_hold', 'return_upright'] = 'prepare'
    stream_id: str = Field(default='default', min_length=1, max_length=128)
    image_width: int | None = Field(default=None, gt=0, le=4096)
    image_height: int | None = Field(default=None, gt=0, le=4096)
    movement_variant: Literal['unknown', 'both_arms_overhead', 'single_arm_overhead'] = 'unknown'
    raised_arm_side: Literal['unknown', 'left', 'right'] = 'unknown'
    bend_direction: Literal['unknown', 'image_left', 'image_right'] = 'unknown'
    keypoints: list[list[float | None]] = Field(min_length=133, max_length=133)
    scores: list[float | None] = Field(min_length=133, max_length=133)

    @model_validator(mode="after")
    def check_pairs(self):
        if not self.session_id.strip() or any(len(p) != 2 for p in self.keypoints):
            raise ValueError("nonblank session_id and exactly 133 [x,y] pairs required")
        return self
