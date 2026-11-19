"""B: stream A's 133-point JSONL to per-frame CSV/JSONL and descriptive statistics.

Run: python -m experiments.detection.extract_features_133 INPUT --output-dir OUTPUT
Python standard library only. Never interprets the file name 'correct' as truth.
"""
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median, pstdev
from tempfile import TemporaryDirectory

from backend.pose_features_133 import (
    DEFAULT_MIN_SCORE, FEATURE_UNITS, FEATURE_VERSION, LAYOUT, extract_features_133,
)


def percentile(values, q):
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _optional_json(path):
    return json.loads(path.read_text()) if path.exists() else None


def export_features(input_path: Path, output_dir: Path, min_score=DEFAULT_MIN_SCORE):
    input_path, output_dir = input_path.resolve(), output_dir.resolve()
    if output_dir == input_path.parent or input_path.is_relative_to(output_dir):
        raise ValueError("write outputs to a separate B-owned directory, not A's source directory")
    metadata = _optional_json(input_path.parent / "metadata.json")
    selection = _optional_json(input_path.parent / "selection.json")
    if metadata is not None and metadata.get("layout") != LAYOUT:
        raise ValueError(f"metadata layout must be {LAYOUT!r}")
    if metadata is not None and "image pixels" not in metadata.get("coordinates", ""):
        raise ValueError("metadata must explicitly identify image-pixel coordinates")
    output_dir.mkdir(parents=True, exist_ok=True)
    names = list(FEATURE_UNITS)
    columns = ["frame_index", "timestamp_ms", "measurement_status"]
    for name in names:
        columns += [name, f"{name}__valid", f"{name}__reason", f"{name}__min_score"]
    values = {name: [] for name in names}
    reasons = {name: Counter() for name in names}
    statuses = Counter()
    digest = hashlib.sha256()
    count = 0
    first_time = last_time = None
    nonincreasing_times = 0
    score_above_one = 0
    with TemporaryDirectory(prefix=".features133-", dir=output_dir) as temporary:
        temp = Path(temporary)
        with input_path.open("rb") as src, (temp / "features.jsonl").open("w") as jout, \
                (temp / "features.csv").open("w", newline="") as cout:
            writer = csv.DictWriter(cout, fieldnames=columns)
            writer.writeheader()
            for line_number, line in enumerate(src, 1):
                digest.update(line)
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    measurement = extract_features_133(raw, min_score=min_score)
                except (ValueError, TypeError, KeyError) as exc:
                    raise ValueError(f"{input_path.name}: line {line_number}: {exc}") from exc
                t = measurement["timestamp_ms"]
                if first_time is None:
                    first_time = t
                if last_time is not None and t <= last_time:
                    nonincreasing_times += 1
                last_time = t
                score_above_one += sum(isinstance(s, (int, float)) and not isinstance(s, bool)
                                       and s > 1 for s in raw["scores"])
                measurement["frame_index"] = count
                jout.write(json.dumps(measurement, ensure_ascii=False, allow_nan=False) + "\n")
                row = dict(frame_index=count, timestamp_ms=t,
                           measurement_status=measurement["measurement_status"])
                statuses[measurement["measurement_status"]] += 1
                for name, item in measurement["features"].items():
                    row[name] = item["value"]
                    row[f"{name}__valid"] = item["valid"]
                    row[f"{name}__reason"] = item["reason"]
                    row[f"{name}__min_score"] = item["min_keypoint_score"]
                    if item["valid"]:
                        values[name].append(item["value"])
                    else:
                        reasons[name][item["reason"]] += 1
                writer.writerow(row)
                count += 1
        if count == 0:
            raise ValueError("input contains no non-empty frames")
        summary = dict(
            source_file=str(input_path), source_sha256=digest.hexdigest(),
            feature_version=FEATURE_VERSION, layout=LAYOUT, frames=count,
            timestamp_range_ms=[first_time, last_time], nonincreasing_timestamps=nonincreasing_times,
            min_score=min_score, min_score_status="PROVISIONAL_NOT_CALIBRATED",
            scores_above_one_preserved=score_above_one,
            source_metadata=metadata, source_selection=selection,
            source_review_status="requires_manual_review",
            all_frames_processed=True, hold_segments_selected=False,
            usage="descriptive measurements only; not correction thresholds or ground truth",
            camera_view_verification="not_performed", image_bounds_check="not_performed_no_dimensions",
            measurement_status_counts=dict(statuses), feature_statistics={},
        )
        if metadata is None:
            summary["layout_warning"] = "133-point COCO layout and pixel coordinates assumed by caller"
        for name, feature_values in values.items():
            stats = dict(unit=FEATURE_UNITS[name], valid_frames=len(feature_values),
                         invalid_frames=count - len(feature_values),
                         invalid_reasons=dict(reasons[name]))
            if feature_values:
                stats.update(min=min(feature_values), max=max(feature_values),
                             mean=mean(feature_values), median=median(feature_values),
                             std=pstdev(feature_values),
                             p05=percentile(feature_values, 0.05), p95=percentile(feature_values, 0.95))
            summary["feature_statistics"][name] = stats
        (temp / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        )
        # Publish only after every input record was successfully processed.
        for name in ("features.jsonl", "features.csv", "summary.json"):
            (temp / name).replace(output_dir / name)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE,
                        help="provisional DWPose score gate, not probability; default 0.5")
    args = parser.parse_args()
    summary = export_features(args.input, args.output_dir, args.min_score)
    print(f"Processed {summary['frames']} frames; measurements only.")
    print(f"Output: {args.output_dir.resolve()}")
    print(json.dumps(summary["measurement_status_counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
