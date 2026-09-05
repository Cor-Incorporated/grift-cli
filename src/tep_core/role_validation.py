"""External role-label classifier validation. Never joins actor identity."""

from __future__ import annotations

import csv
import math
from collections import Counter
from pathlib import Path
from typing import Any

from tep_core.secrets_guard import InputValidationError

LABELS = ("Backend", "Frontend", "Mobile", "DevOps", "DataScientist")
SAMPLE_WARNING = "n=40 smoke sample. Do not claim model performance or employment-role accuracy."
ID_COLUMNS = frozenset({"source_row", "role_label"})
FEATURE_COLUMNS = frozenset(
    {
        "bio_backend",
        "bio_frontend",
        "bio_devops",
        "bio_data",
        "bio_java",
        "bio_javascript",
        "bio_python",
        "rate_java",
        "rate_python",
        "rate_typescript",
        "author_javascript",
        "author_typescript",
    }
)


def load_role_sample(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        expected = ID_COLUMNS | FEATURE_COLUMNS
        if columns != expected:
            missing = sorted(expected - columns)
            extra = sorted(columns - expected)
            raise InputValidationError(
                f"role sample columns mismatch: missing={missing}, extra={extra}"
            )
        rows = list(reader)
    if not rows:
        raise InputValidationError("role sample is empty")
    source_rows: set[str] = set()
    for index, row in enumerate(rows):
        if row.get("role_label") not in LABELS:
            raise InputValidationError(f"unknown role_label: {row.get('role_label')}")
        if "canonical_id" in row or "email" in row or "actor" in row:
            raise InputValidationError("role sample cannot carry actor identity fields")
        source_row = (row.get("source_row") or "").strip()
        if not source_row or source_row in source_rows:
            raise InputValidationError(f"role sample duplicate/missing source_row at row {index}")
        source_rows.add(source_row)
        for key in FEATURE_COLUMNS:
            value = row.get(key)
            if value is None or not value.strip():
                raise InputValidationError(f"role sample row {index}: missing feature {key}")
            try:
                number = float(value)
            except ValueError as exc:
                raise InputValidationError(
                    f"role sample row {index}: feature {key} must be numeric"
                ) from exc
            if not math.isfinite(number) or number < 0:
                raise InputValidationError(
                    f"role sample row {index}: feature {key} must be finite and >= 0"
                )
    support = Counter(row["role_label"] for row in rows)
    missing_classes = [label for label in LABELS if support[label] == 0]
    if missing_classes:
        raise InputValidationError(f"role sample missing classes: {missing_classes}")
    return rows


def _num(row: dict[str, str], key: str) -> float:
    return float(row[key])


def predict_label(row: dict[str, str]) -> str:
    scores = {
        "Backend": _num(row, "bio_backend") + _num(row, "bio_java") + _num(row, "rate_java"),
        "Frontend": _num(row, "bio_frontend")
        + _num(row, "rate_typescript")
        + 0.01 * _num(row, "author_javascript"),
        "Mobile": 0.02 * _num(row, "author_typescript") + 0.01 * _num(row, "author_javascript"),
        "DevOps": _num(row, "bio_devops"),
        "DataScientist": _num(row, "bio_data") + _num(row, "rate_python"),
    }
    return max(LABELS, key=lambda name: scores[name])


def _prf(truth: list[str], pred: list[str], label: str) -> tuple[float, float, float, int]:
    tp = sum(1 for left, right in zip(truth, pred) if left == label and right == label)
    fp = sum(1 for left, right in zip(truth, pred) if left != label and right == label)
    fn = sum(1 for left, right in zip(truth, pred) if left == label and right != label)
    support = sum(1 for item in truth if item == label)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return round(precision, 4), round(recall, 4), round(f1, 4), support


def validate_role_sample(path: Path) -> dict[str, Any]:
    rows = load_role_sample(path)
    truth = [row["role_label"] for row in rows]
    pred = [predict_label(row) for row in rows]
    per_class = {}
    matrix = {label: {other: 0 for other in LABELS} for label in LABELS}
    for left, right in zip(truth, pred):
        matrix[left][right] += 1
    precisions = []
    recalls = []
    f1s = []
    weights = []
    for label in LABELS:
        precision, recall, f1, support = _prf(truth, pred, label)
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
            "title": f"{label}ラベルに対する分類器の検証結果",
        }
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)
        weights.append(support)
    total = len(rows)

    def weighted(values: list[float]) -> float:
        return round(sum(value * weight for value, weight in zip(values, weights)) / total, 4)

    accuracy = round(sum(1 for left, right in zip(truth, pred) if left == right) / total, 4)
    return {
        "kind": "observed",
        "unit": "profile",
        "task": "external_classifier_validation",
        "sample_size": total,
        "effective_sample_size": total,
        "sample_size_warning": SAMPLE_WARNING,
        "class_support": dict(Counter(truth)),
        "accuracy": accuracy,
        "macro_precision": round(sum(precisions) / len(LABELS), 4),
        "macro_recall": round(sum(recalls) / len(LABELS), 4),
        "macro_f1": round(sum(f1s) / len(LABELS), 4),
        "weighted_precision": weighted(precisions),
        "weighted_recall": weighted(recalls),
        "weighted_f1": weighted(f1s),
        "confusion_matrix": matrix,
        "per_class": per_class,
        "limitations": [
            SAMPLE_WARNING,
            "This is not an actor identity, employment role, or fit score.",
            "Do not join this table to grift actor reports.",
        ],
    }


def refuse_actor_join() -> None:
    raise InputValidationError("role_ground_truth_sample.csv cannot be joined to actor identity")
