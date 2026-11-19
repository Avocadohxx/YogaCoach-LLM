"""Owner B: geometry/contract invariants; NOT measured real-video accuracy."""
import json
import math
import unittest
from pathlib import Path

from pydantic import ValidationError

from backend.pose_analyzer import (
    Point2D, MeasurementUnavailable, analyze_frame, compute_elbow_angle,
)
from backend.schemas import AnalysisResult, PoseFrame
from experiments.detection.synthetic_day1 import make_frame, make_mocks


def result(raw):
    return analyze_frame(PoseFrame.model_validate(raw))


def values(raw):
    return {o.name: o.value for o in result(raw).observations}


class GeometryTests(unittest.TestCase):
    def test_straight_torso_and_arms(self):
        measured = values(make_frame())
        self.assertAlmostEqual(measured["shoulder_height_diff"], 0)
        self.assertAlmostEqual(measured["torso_tilt_deg"], 0)
        self.assertAlmostEqual(measured["left_elbow_angle_deg"], 180)

    def test_known_elbow_angles_and_degenerate_segment(self):
        self.assertAlmostEqual(compute_elbow_angle(
            Point2D(0, 10), Point2D(0, 0), Point2D(10, 0)), 90)
        self.assertAlmostEqual(compute_elbow_angle(
            Point2D(-10, 0), Point2D(0, 0), Point2D(10, 0)), 180)
        with self.assertRaises(MeasurementUnavailable):
            compute_elbow_angle(Point2D(0, 0), Point2D(0, 0), Point2D(10, 0))

    def test_translation_invariance(self):
        original = make_frame()
        moved = make_frame()
        for p in moved["landmarks"]:
            p["x"] += 0.02
            p["y"] -= 0.02
        for k, v in values(original).items():
            self.assertAlmostEqual(v, values(moved)[k])

    def test_uniform_body_scale_invariance(self):
        original = make_frame("side_bend")
        scaled = make_frame("side_bend")
        for p in scaled["landmarks"]:
            p["x"] = 0.5 + (p["x"] - 0.5) * 0.7
            p["y"] = 0.5 + (p["y"] - 0.5) * 0.7
        for k, v in values(original).items():
            self.assertAlmostEqual(v, values(scaled)[k])

    def test_aspect_ratio_uses_actual_image_dimensions(self):
        raw = make_frame()
        for i in (11, 12):
            raw["landmarks"][i]["x"] += 216 / 1280
        self.assertAlmostEqual(values(raw)["torso_tilt_deg"], 45)
        # Same pixel geometry represented on a square image must give same angle.
        square = make_frame()
        square["image_width"] = 720
        for old, new in zip(raw["landmarks"], square["landmarks"]):
            new["x"] = (old["x"] - 0.5) * 1280 / 720 + 0.5
        self.assertAlmostEqual(values(square)["torso_tilt_deg"], 45)

    def test_shoulder_change_is_measured_but_never_corrected(self):
        out = result(make_frame("shoulder_difference"))
        self.assertGreater(next(o.value for o in out.observations
                                if o.name == "shoulder_height_diff"), 0)
        self.assertEqual(out.assessment_status, "uncalibrated")
        self.assertFalse(out.feedback_allowed)
        self.assertEqual(out.deviations, [])

    def test_side_bend_is_not_judged_by_upright_rules(self):
        out = result(make_frame("side_bend"))
        self.assertNotEqual(values(make_frame("side_bend"))["torso_tilt_deg"], 0)
        self.assertFalse(out.feedback_allowed)
        self.assertEqual(out.deviations, [])

    def test_mirroring_reverses_image_angle_not_elbow_identity(self):
        raw = make_frame("side_bend")
        before = values(raw)
        for p in raw["landmarks"]:
            p["x"] = 1 - p["x"]
        after = values(raw)
        self.assertAlmostEqual(after["torso_tilt_deg"], -before["torso_tilt_deg"])
        self.assertAlmostEqual(after["left_elbow_angle_deg"], before["left_elbow_angle_deg"])


class QualityAndSchemaTests(unittest.TestCase):
    def test_wrist_occlusion_does_not_remove_torso_measurement(self):
        raw = make_frame()
        raw["landmarks"][15]["visibility"] = 0.0
        out = result(raw)
        obs = {o.name: o for o in out.observations}
        self.assertTrue(obs["torso_tilt_deg"].valid)
        self.assertFalse(obs["left_elbow_angle_deg"].valid)
        self.assertIsNone(obs["left_elbow_angle_deg"].value)
        self.assertEqual(out.tracking_quality, "partial")

    def test_no_visible_person_cannot_get_feedback(self):
        out = result(make_frame("occluded"))
        self.assertEqual(out.assessment_status, "not_assessable")
        self.assertEqual(out.tracking_quality, "poor")
        self.assertFalse(out.feedback_allowed)

    def test_side_camera_and_prepare_phase_do_not_allow_correction(self):
        for field, value in (("camera_view", "side"), ("phase", "prepare")):
            with self.subTest(field=field):
                raw = make_frame()
                raw[field] = value
                self.assertEqual(result(raw).assessment_status, "not_assessable")
                self.assertFalse(result(raw).feedback_allowed)

    def test_outside_coordinates_are_quality_failure_not_protocol_error(self):
        raw = make_frame()
        raw["landmarks"][15]["x"] = 1.2
        out = result(raw)
        obs = next(o for o in out.observations if o.name == "left_elbow_angle_deg")
        self.assertEqual(obs.reason, "required_landmark_out_of_frame")

    def test_coincident_points_are_not_a_valid_straight_person(self):
        raw = make_frame()
        for p in raw["landmarks"]:
            p.update(x=0.5, y=0.5, visibility=0.99)
        out = result(raw)
        self.assertEqual(out.assessment_status, "not_assessable")
        self.assertTrue(all(o.value is None for o in out.observations))

    def test_contract_rejects_bad_lengths_numbers_and_fields(self):
        cases = []
        for n in (0, 1, 32, 34):
            raw = make_frame()
            raw["landmarks"] = (raw["landmarks"] * 2)[:n]
            cases.append(raw)
        for field, value in (("image_width", 0), ("image_height", -1),
                             ("pose_id", "unknown"), ("timestamp_ms", -1),
                             ("frame_seq", True), ("side", "left"),
                             ("session_id", "   ")):
            raw = make_frame()
            raw[field] = value
            cases.append(raw)
        for field, value in (("x", math.nan), ("z", math.inf),
                             ("visibility", -0.1), ("visibility", 1.1)):
            raw = make_frame()
            raw["landmarks"][11][field] = value
            cases.append(raw)
        raw = make_frame("side_bend")
        raw["side"] = None
        cases.append(raw)
        for raw in cases:
            with self.subTest(raw=str(raw)[:100]):
                with self.assertRaises(ValidationError):
                    PoseFrame.model_validate(raw)

    def test_all_mock_contracts_and_real_api_guard(self):
        mocks = make_mocks()
        for obj in mocks.values():
            AnalysisResult.model_validate(obj)
        bad = result(make_frame()).model_dump()
        bad["feedback_allowed"] = True
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(bad)

    def test_committed_fixtures_match_generator(self):
        root = Path(__file__).resolve().parents[1]
        for kind in ("normal", "shoulder_difference", "occluded", "side_bend"):
            stored = json.loads((root / f"experiments/detection/fixtures/{kind}.json").read_text())
            self.assertEqual(stored, make_frame(kind))
        for kind, expected in make_mocks().items():
            path = root / f"contracts/mock/b_day1/analysis_{kind}.json"
            self.assertEqual(json.loads(path.read_text()), expected)


class ApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_health_and_analyze_route(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        response = self.client.post("/api/analyze", json=make_frame())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["feedback_allowed"])
        AnalysisResult.model_validate(response.json())

    def test_invalid_schema_is_422_and_low_visibility_is_200(self):
        raw = make_frame()
        raw["landmarks"].pop()
        self.assertEqual(self.client.post("/api/analyze", json=raw).status_code, 422)
        response = self.client.post("/api/analyze", json=make_frame("occluded"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["assessment_status"], "not_assessable")

    def test_openapi_lists_new_input_and_response(self):
        spec = self.client.get("/openapi.json").json()
        route = spec["paths"]["/api/analyze"]["post"]
        self.assertIn("PoseFrame", str(route["requestBody"]))
        self.assertIn("AnalysisResult", str(route["responses"]["200"]))


if __name__ == "__main__":
    unittest.main()
