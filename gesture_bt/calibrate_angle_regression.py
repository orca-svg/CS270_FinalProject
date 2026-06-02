#!/usr/bin/env python3
"""
Fit a camera-coordinate to turret-angle calibration model.

This script trains the quadratic regression used by the launcher:

    pan_angle  = a0 + a1*x + a2*y + a3*x*y + a4*x^2 + a5*y^2
    tilt_angle = b0 + b1*x + b2*y + b3*x*y + b4*x^2 + b5*y^2

Input CSV rows should contain measured target image coordinates and the
pan/tilt angles that actually hit the fixed target. The resulting weights can
be copied into the vision controller or saved as JSON for later loading.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


FEATURE_NAMES = ("1", "x", "y", "x*y", "x^2", "y^2")
REQUIRED_SAMPLE_COUNT = len(FEATURE_NAMES)


PAN_COLUMN_ALIASES = (
    "pan_angle",
    "pan",
    "lr_angle",
    "left_right_angle",
    "left_right",
)
TILT_COLUMN_ALIASES = (
    "tilt_angle",
    "tilt",
    "ud_angle",
    "up_down_angle",
    "up_down",
)


def make_feature_row(x: float, y: float) -> list[float]:
    """Build one [1, x, y, x*y, x^2, y^2] feature row."""
    return [1.0, x, y, x * y, x**2, y**2]


def find_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str:
    normalized = {name.strip().lower(): name for name in fieldnames}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    raise ValueError(f"CSV must contain one of these columns: {', '.join(candidates)}")


def read_calibration_csv(path: Path) -> list[list[float]]:
    with path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError("CSV file has no header row.")

        x_col = find_column(reader.fieldnames, ("x", "target_x", "pixel_x"))
        y_col = find_column(reader.fieldnames, ("y", "target_y", "pixel_y"))
        pan_col = find_column(reader.fieldnames, PAN_COLUMN_ALIASES)
        tilt_col = find_column(reader.fieldnames, TILT_COLUMN_ALIASES)

        rows: list[list[float]] = []
        for line_no, row in enumerate(reader, start=2):
            try:
                rows.append(
                    [
                        float(row[x_col]),
                        float(row[y_col]),
                        float(row[pan_col]),
                        float(row[tilt_col]),
                    ]
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid numeric value on CSV line {line_no}: {row}") from exc

    if len(rows) < REQUIRED_SAMPLE_COUNT:
        raise ValueError(
            f"At least {REQUIRED_SAMPLE_COUNT} calibration samples are required; "
            f"got {len(rows)}."
        )
    return rows


def solve_linear_system(matrix: list[list[float]], values: list[float]) -> list[float]:
    """Solve Ax=b with Gauss-Jordan elimination and partial pivoting."""
    size = len(values)
    augmented = [row[:] + [value] for row, value in zip(matrix, values)]

    for col in range(size):
        pivot_row = max(range(col, size), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot_row][col]) < 1e-12:
            raise ValueError(
                "Calibration matrix is singular. Add more varied calibration samples."
            )
        augmented[col], augmented[pivot_row] = augmented[pivot_row], augmented[col]

        pivot = augmented[col][col]
        augmented[col] = [value / pivot for value in augmented[col]]

        for row in range(size):
            if row == col:
                continue
            factor = augmented[row][col]
            augmented[row] = [
                current - factor * pivot_value
                for current, pivot_value in zip(augmented[row], augmented[col])
            ]

    return [row[-1] for row in augmented]


def least_squares(features: list[list[float]], targets: list[float]) -> list[float]:
    """Fit weights by solving the normal equation (X^T X)w = X^T y."""
    feature_count = len(features[0])
    xtx = [[0.0 for _ in range(feature_count)] for _ in range(feature_count)]
    xty = [0.0 for _ in range(feature_count)]

    for feature_row, target in zip(features, targets):
        for i in range(feature_count):
            xty[i] += feature_row[i] * target
            for j in range(feature_count):
                xtx[i][j] += feature_row[i] * feature_row[j]

    return solve_linear_system(xtx, xty)


def fit_weights(data: list[list[float]]) -> tuple[list[float], list[float]]:
    features = [make_feature_row(row[0], row[1]) for row in data]
    pan_angle = [row[2] for row in data]
    tilt_angle = [row[3] for row in data]

    pan_weights = least_squares(features, pan_angle)
    tilt_weights = least_squares(features, tilt_angle)
    return pan_weights, tilt_weights


def predict_angles(
    x: float,
    y: float,
    pan_weights: list[float],
    tilt_weights: list[float],
) -> tuple[float, float]:
    features = make_feature_row(x, y)
    pan_angle = sum(feature * weight for feature, weight in zip(features, pan_weights))
    tilt_angle = sum(feature * weight for feature, weight in zip(features, tilt_weights))
    return pan_angle, tilt_angle


def compute_metrics(
    data: list[list[float]],
    pan_weights: list[float],
    tilt_weights: list[float],
) -> dict[str, float]:
    pan_abs_error_sum = 0.0
    tilt_abs_error_sum = 0.0
    total_squared_error_sum = 0.0

    for x, y, actual_pan, actual_tilt in data:
        pred_pan, pred_tilt = predict_angles(x, y, pan_weights, tilt_weights)
        pan_error = pred_pan - actual_pan
        tilt_error = pred_tilt - actual_tilt
        pan_abs_error_sum += abs(pan_error)
        tilt_abs_error_sum += abs(tilt_error)
        total_squared_error_sum += pan_error**2 + tilt_error**2

    sample_count = len(data)

    return {
        "pan_mae_deg": pan_abs_error_sum / sample_count,
        "tilt_mae_deg": tilt_abs_error_sum / sample_count,
        "combined_rmse_deg": (total_squared_error_sum / sample_count) ** 0.5,
        "sample_count": float(sample_count),
    }


def format_equation(label: str, variable: str, weights: list[float]) -> str:
    terms = [f"{weights[0]:.10g}"]
    for weight, feature_name in zip(weights[1:], FEATURE_NAMES[1:]):
        sign = "+" if weight >= 0 else "-"
        terms.append(f"{sign} {abs(weight):.10g}*{feature_name}")
    return f"{label}: {variable} = " + " ".join(terms)


def write_template(path: Path) -> None:
    template = """x,y,pan_angle,tilt_angle
320,240,90,45
260,240,84,45
380,240,96,45
320,180,90,51
320,300,90,39
260,180,84,51
380,300,96,39
"""
    path.write_text(template, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train quadratic pan/tilt calibration weights from fixed-target data."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="Calibration CSV with x,y,pan_angle,tilt_angle columns.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Optional JSON output path for learned weights and fit metrics.",
    )
    parser.add_argument(
        "--write-template",
        type=Path,
        help="Write a starter calibration CSV template and exit.",
    )
    parser.add_argument(
        "--predict",
        nargs=2,
        metavar=("X", "Y"),
        type=float,
        help="Also print the predicted pan/tilt angle for one target coordinate.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.write_template:
        write_template(args.write_template)
        print(f"Wrote calibration CSV template: {args.write_template}")
        return 0

    if args.csv is None:
        print("error: --csv is required unless --write-template is used", file=sys.stderr)
        return 2

    data = read_calibration_csv(args.csv)
    pan_weights, tilt_weights = fit_weights(data)
    metrics = compute_metrics(data, pan_weights, tilt_weights)

    print(format_equation("Pan model", "pan_angle", pan_weights))
    print(format_equation("Tilt model", "tilt_angle", tilt_weights))
    print()
    print("Python constants:")
    print(f"PAN_WEIGHTS = {pan_weights.tolist()}")
    print(f"TILT_WEIGHTS = {tilt_weights.tolist()}")
    print()
    print("Fit metrics:")
    for name, value in metrics.items():
        if name == "sample_count":
            print(f"  {name}: {int(value)}")
        else:
            print(f"  {name}: {value:.4f}")

    if args.predict:
        target_x, target_y = args.predict
        pred_pan, pred_tilt = predict_angles(
            target_x,
            target_y,
            pan_weights,
            tilt_weights,
        )
        print()
        print(f"Prediction for x={target_x:g}, y={target_y:g}:")
        print(f"  pan_angle: {pred_pan:.2f}")
        print(f"  tilt_angle: {pred_tilt:.2f}")

    if args.out:
        payload = {
            "model": "quadratic_xy_to_pan_tilt",
            "features": FEATURE_NAMES,
            "pan_weights": pan_weights.tolist(),
            "tilt_weights": tilt_weights.tolist(),
            "metrics": metrics,
        }
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print()
        print(f"Wrote weights: {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
