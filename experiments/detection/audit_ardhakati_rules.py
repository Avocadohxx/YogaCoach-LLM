"""Reproducible descriptive audit of the two supplied side-bend feature clips.

No video phase labels, camera verification, or medical thresholds are inferred.
Run from the repository root with python3 -m experiments.detection.audit_ardhakati_rules.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from backend.pose_features_133 import extract_features_133

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = Path('/Users/tzc/Downloads/YogaCoach-LLM-main/experiments/detection/outputs')
FEATURES = (
    'shoulder_height_diff_px', 'shoulder_height_diff', 'torso_tilt_deg',
    'left_elbow_angle_deg', 'right_elbow_angle_deg',
    'left_arm_torso_angle_deg', 'right_arm_torso_angle_deg',
    'ankle_spacing_shoulder_ratio',
)
KEYPOINT_IDS = [5, 6, 7, 8, 9, 10, 11, 12, 15, 16]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quantile(values, p):
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def describe(values):
    if not values:
        return {'count': 0}
    return dict(count=len(values), min=min(values), max=max(values),
                mean=statistics.mean(values), median=statistics.median(values),
                std=statistics.pstdev(values), p05=quantile(values, .05),
                p95=quantile(values, .95))


def value(row, name):
    return row['features'][name]['value']


def runs(rows, predicate):
    sequences, current = [], []
    for row in rows:
        if predicate(row):
            current.append(row)
        else:
            if current:
                sequences.append(current)
            current = []
    if current:
        sequences.append(current)
    records = [dict(start_ms=s[0]['timestamp_ms'], end_ms=s[-1]['timestamp_ms'],
                    elapsed_ms=s[-1]['timestamp_ms'] - s[0]['timestamp_ms'],
                    frames=len(s)) for s in sequences]
    return dict(run_count=len(records),
                runs_ge_1500ms=sum(r['elapsed_ms'] >= 1500 for r in records),
                longest=sorted(records, key=lambda r: r['elapsed_ms'], reverse=True)[:5],
                timestamp_semantics='last qualifying timestamp minus first; no invented trailing frame duration')


def audit_clip(directory):
    paths = {n: directory / n for n in ('features.jsonl', 'features.csv', 'summary.json')}
    rows = [json.loads(line) for line in paths['features.jsonl'].open()]
    with paths['features.csv'].open(newline='') as stream:
        csv_rows = list(csv.DictReader(stream))
    summary = json.loads(paths['summary.json'].read_text())
    mismatches = Counter()
    if len(csv_rows) != len(rows):
        mismatches['csv_row_count'] += 1
    if summary['frames'] != len(rows):
        mismatches['summary_frame_count'] += 1
    for csv_row, row in zip(csv_rows, rows):
        for key in ('frame_index', 'timestamp_ms'):
            if int(csv_row[key]) != row[key]:
                mismatches['csv_' + key] += 1
        if csv_row['measurement_status'] != row['measurement_status']:
            mismatches['csv_measurement_status'] += 1
        for name, feature in row['features'].items():
            if not math.isclose(float(csv_row[name]), feature['value'], rel_tol=1e-12, abs_tol=1e-12):
                mismatches['csv_feature_value'] += 1
            if (csv_row[name + '__valid'] == 'True') != feature['valid']:
                mismatches['csv_feature_valid'] += 1
            if (csv_row[name + '__reason'] or None) != feature['reason']:
                mismatches['csv_feature_reason'] += 1
            if not math.isclose(float(csv_row[name + '__min_score']), feature['min_keypoint_score'], rel_tol=1e-12):
                mismatches['csv_feature_score'] += 1
    times = [row['timestamp_ms'] for row in rows]
    differences = [b - a for a, b in zip(times, times[1:])]
    stats = {name: describe([value(r, name) for r in rows]) for name in FEATURES}
    for name, actual in stats.items():
        expected = summary['feature_statistics'][name]
        for key in ('min', 'max', 'mean', 'median', 'std', 'p05', 'p95'):
            if not math.isclose(actual[key], expected[key], rel_tol=1e-10, abs_tol=1e-10):
                mismatches['summary_statistic_' + key] += 1
        if expected['valid_frames'] != actual['count'] or expected['invalid_frames'] != 0:
            mismatches['summary_feature_counts'] += 1
    if summary['timestamp_range_ms'] != [times[0], times[-1]]:
        mismatches['summary_timestamp_range'] += 1
    source = Path(summary['source_file'])
    raw_report = {'path': str(source), 'available': source.is_file()}
    if source.is_file():
        raw = [json.loads(line) for line in source.open()]
        all_scores = [s for row in raw for s in row['scores']]
        body_scores = [row['scores'][i] for row in raw for i in KEYPOINT_IDS]
        raw_report.update(sha256=sha256(source), declared_sha256=summary['source_sha256'],
                          hash_matches=sha256(source) == summary['source_sha256'], frames=len(raw),
                          all_133_scores=describe(all_scores), relevant_body_scores=describe(body_scores),
                          scores_above_one=sum(s > 1 for s in all_scores),
                          score_semantics='raw model outputs; values above 1 preserved; not calibrated probabilities')
        raw_report['scores_by_relevant_keypoint'] = {
            str(i): describe([frame['scores'][i] for frame in raw]) for i in KEYPOINT_IDS
        }
        if len(raw) != len(rows):
            mismatches['raw_row_count'] += 1
        for frame, supplied in zip(raw, rows):
            recomputed = extract_features_133(frame, min_score=summary['min_score'])
            if frame['timestamp_ms'] != supplied['timestamp_ms']:
                mismatches['raw_timestamp'] += 1
            for name in FEATURES:
                actual, expected = recomputed['features'][name], supplied['features'][name]
                for field in ('value', 'min_keypoint_score'):
                    if not math.isclose(actual[field], expected[field], rel_tol=1e-12, abs_tol=1e-12):
                        mismatches['raw_recomputed_' + field] += 1
                if actual['valid'] != expected['valid']:
                    mismatches['raw_recomputed_valid'] += 1
        if raw_report['scores_above_one'] != summary['scores_above_one_preserved']:
            mismatches['summary_scores_above_one'] += 1
        if not raw_report['hash_matches']:
            mismatches['raw_sha256'] += 1
    predicates = {
        'all_frames': lambda r: True,
        'torso_upright_abs_le_5': lambda r: abs(value(r, 'torso_tilt_deg')) <= 5,
        'torso_image_left_lt_minus15': lambda r: value(r, 'torso_tilt_deg') < -15,
        'torso_image_right_gt_15': lambda r: value(r, 'torso_tilt_deg') > 15,
        'both_upper_arms_gt_150': lambda r: min(value(r, 'left_arm_torso_angle_deg'), value(r, 'right_arm_torso_angle_deg')) > 150,
        'left_arm_gt150_right_lt60': lambda r: value(r, 'left_arm_torso_angle_deg') > 150 and value(r, 'right_arm_torso_angle_deg') < 60,
        'right_arm_gt150_left_lt60': lambda r: value(r, 'right_arm_torso_angle_deg') > 150 and value(r, 'left_arm_torso_angle_deg') < 60,
        'image_left_bend_left_arm_gt120': lambda r: value(r, 'torso_tilt_deg') < -15 and value(r, 'left_arm_torso_angle_deg') > 120,
        'image_right_bend_right_arm_gt120': lambda r: value(r, 'torso_tilt_deg') > 15 and value(r, 'right_arm_torso_angle_deg') > 120,
    }
    buckets = {}
    for name, predicate in predicates.items():
        selected = [r for r in rows if predicate(r)]
        buckets[name] = {'frames': len(selected), 'fraction': len(selected) / len(rows),
                         'statistics': {f: describe([value(r, f) for r in selected]) for f in FEATURES},
                         'runs': runs(rows, predicate)}
    threshold_runs = {}
    for side in ('left', 'right'):
        elbow = side + '_elbow_angle_deg'
        for cutoff in (145, 150, 155, 160, 165):
            threshold_runs[f'{side}_elbow_lt_{cutoff}_all'] = runs(rows, lambda r, f=elbow, c=cutoff: value(r, f) < c)
            bend = (lambda r: value(r, 'torso_tilt_deg') < -15) if side == 'left' else (lambda r: value(r, 'torso_tilt_deg') > 15)
            threshold_runs[f'{side}_elbow_lt_{cutoff}_matching_image_bend15'] = runs(rows, lambda r, f=elbow, c=cutoff, b=bend: b(r) and value(r, f) < c)
        for cutoff in (130, 140, 150, 160):
            arm = side + '_arm_torso_angle_deg'
            bend = (lambda r: value(r, 'torso_tilt_deg') < -15) if side == 'left' else (lambda r: value(r, 'torso_tilt_deg') > 15)
            threshold_runs[f'{side}_arm_lt_{cutoff}_matching_image_bend15'] = runs(rows, lambda r, f=arm, c=cutoff, b=bend: b(r) and value(r, f) < c)
    for cutoff in (.35, .4, .45):
        threshold_runs[f'ankle_shoulder_ratio_gt_{cutoff}_all'] = runs(rows, lambda r, c=cutoff: value(r, 'ankle_spacing_shoulder_ratio') > c)
    for cutoff in (30, 35, 40):
        threshold_runs[f'abs_torso_tilt_gt_{cutoff}_all'] = runs(rows, lambda r, c=cutoff: abs(value(r, 'torso_tilt_deg')) > c)
    return {
        'source_directory': str(directory), 'files_sha256': {n: sha256(p) for n, p in paths.items()},
        'frames': len(rows), 'timestamp_range_ms': [times[0], times[-1]],
        'timestamp_deltas_ms': dict(sorted(Counter(differences).items())),
        'nonincreasing_timestamps': sum(d <= 0 for d in differences),
        'measurement_status_counts': dict(Counter(r['measurement_status'] for r in rows)),
        'camera_view': summary['source_selection']['camera_view'],
        'source_selection': summary['source_selection'], 'source_metadata': summary['source_metadata'],
        'all_file_consistency_checks_passed': not mismatches, 'mismatch_counts': dict(mismatches),
        'raw_keypoints_verification': raw_report, 'all_frame_statistics': stats,
        'geometric_buckets_NOT_hold_labels': buckets,
        'threshold_continuous_runs_NOT_validated_events': threshold_runs,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-dir', type=Path, default=DEFAULT_BASE)
    parser.add_argument('--output', type=Path, default=ROOT / 'experiments/detection/ardhakati_rule_audit.json')
    args = parser.parse_args()
    report = {
        'schema_version': 'ardhakati-descriptive-audit-v1',
        'assumptions': [
            'correct/incorrect are filename labels, not per-frame correctness ground truth',
            'angle_1_unverified is not a verified frontal camera view',
            'signed torso tilt refers to image x, not anatomical left/right; mirroring unresolved',
            'geometric buckets include transitions and are not independently verified hold segments',
            'arm-selected buckets cannot validate arm thresholds; selection would be circular',
            'one clip per label cannot establish sensitivity, specificity, cross-person robustness, or clinical standards',
        ],
        'clips': {label: audit_clip(args.base_dir / f'ardhakati_chakrasana_rtmx_{label}')
                  for label in ('correct', 'incorrect')},
        'design_recommendations': {
            'variant_warning': 'Neither clip contains a frame with both upper-arm/trunk angles >150 degrees. Signed bend buckets show one raised arm and one lowered arm. These clips support a one-arm variant preview, not calibration of the requested two-arms-overhead variant.',
            'safe_default': 'Unreviewed rules off, unknown phase and unverified view block feedback. Explicit exploratory opt-in and declared compatible variant are required for demo replay.',
            'elbow_draft': {'trigger_lt_deg': 150, 'clear_ge_deg': 160, 'min_duration_ms': 1500,
                            'clear_duration_ms': 700, 'max_gap_ms': 500,
                            'scope': 'Only the arm declared raised by the current independently supplied phase/variant; both elbows for a separately verified two-arm variant.',
                            'evidence': 'Supplied correct clip has no elbow below 150 degrees. Incorrect left elbow stays below 150 for 7265ms overall, including 1633ms in the <-15deg image-left bend bucket. Right elbow deviations are shorter and overlapping.',
                            'limitations': 'Conservative engineering demo, not yoga instruction; 160deg recovery is a hysteresis design choice, not a percentile estimate; upper-arm selection must not be needed to make an elbow error assessable.'},
            'monitor_only': [
                'Torso side-bend amplitude and too-little/too-much bend: no reviewed target or hold windows; do not encourage deeper bend from these clips.',
                'Upper-arm/trunk angle: correct bend phases have raised-arm median around139–144deg, so 165deg upright-overhead threshold causes false candidates.',
                'Stance ratio: incorrect has >0.4 for11131ms early, but human stance vs camera/rotation/subject effect is unverified; shoulder denominator changes with side-bend.',
                'Shoulder height difference is expected to increase in side-bend; never reuse the mountain leveling rule.',
                'Hip centering/motion, head alignment, palms together, depressed shoulders, body coplanarity, and weight distribution cannot be established from the existing eight scalar features.',
            ],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'output': str(args.output), 'clips': {
        key: {'frames': value['frames'], 'consistency_passed': value['all_file_consistency_checks_passed']}
        for key, value in report['clips'].items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
