"""Deterministic pincode aggregation from a pattern catalog."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import pandas as pd

from app.analysis.behaviour_actions import enrich_profile_with_behaviour
from app.analysis.business_impact import enrich_profile_with_customers
from app.analysis.domain_metrics import enrich_profile_with_domain_metrics
from app.config import MEAN_RELATIVE, MIN_N, SHARE_DELTA


def _matches(row: dict, filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        if row.get(key) != expected:
            return False
    return True


def _share(values: list[Any], positive_values: list[Any] | None, focus_value: Any | None) -> tuple[float | None, int]:
    present = [value for value in values if value not in (None, "")]
    if not present:
        return None, 0
    if positive_values:
        yes = sum(1 for value in present if value in positive_values)
        return yes / len(present), len(present)
    if focus_value is not None:
        yes = sum(1 for value in present if value == focus_value)
        return yes / len(present), len(present)
    # Yes/No default
    usable = [value for value in present if value in {"Yes", "No"}]
    if not usable:
        return None, 0
    return sum(1 for value in usable if value == "Yes") / len(usable), len(usable)


def _mean(values: list[Any]) -> tuple[float | None, int]:
    nums = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    if not nums:
        return None, 0
    return sum(nums) / len(nums), len(nums)


def _distribution(values: list[Any], top: int = 8) -> tuple[dict[str, float] | None, int]:
    present = [str(value) for value in values if value not in (None, "")]
    if not present:
        return None, 0
    counts = Counter(present)
    total = len(present)
    items = counts.most_common(top)
    return {key: count / total for key, count in items}, total


def _metric_on_rows(
    rows: list[dict],
    field: str,
    method: str,
    positive_values: list[Any] | None = None,
    focus_value: Any | None = None,
) -> tuple[Any, int]:
    values = [row.get(field) for row in rows]
    if method in {"share", "rate", "ratio"}:
        return _share(values, positive_values, focus_value)
    if method == "mean":
        return _mean(values)
    if method in {"distribution", "top_values"}:
        return _distribution(values)
    return None, 0


def _gap_score(method: str, value: float, baseline: float, n: int) -> float:
    delta = value - baseline
    if method == "mean":
        scale = abs(delta) / abs(baseline) if baseline else abs(delta)
        return scale * n
    return abs(delta) * n


def _keep(method: str, value: float, baseline: float) -> bool:
    delta = value - baseline
    if method == "mean":
        if baseline == 0:
            return abs(delta) > 0
        return abs(delta) / abs(baseline) >= MEAN_RELATIVE
    return abs(delta) >= SHARE_DELTA


def aggregate_by_pincode(rows: list[dict], catalog: dict) -> list[dict]:
    if not rows:
        return []
    frame = pd.DataFrame(rows)
    if "zip_code" not in frame.columns:
        raise ValueError("rows missing zip_code")

    by_zip: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        zip_code = row.get("zip_code")
        if not zip_code:
            continue
        by_zip[str(zip_code)].append(row)

    state_rows = rows
    profiles: list[dict] = []

    metric_specs: list[dict] = []
    for outcome in catalog.get("outcomes") or []:
        name = outcome.get("metric") or outcome["field"]
        if not isinstance(name, str):
            continue
        metric_specs.append({
            "kind": "outcome",
            "name": name,
            "field": outcome["field"],
            "method": outcome["method"],
            "positive_values": outcome.get("positive_values"),
            "focus_value": outcome.get("focus_value"),
            "label": name,
        })
    for driver in catalog.get("drivers") or []:
        name = driver.get("metric") or driver["field"]
        if not isinstance(name, str):
            continue
        metric_specs.append({
            "kind": "driver",
            "name": name,
            "field": driver["field"],
            "method": driver["method"],
            "positive_values": driver.get("positive_values"),
            "focus_value": driver.get("focus_value"),
            "label": driver["field"],
        })

    for zip_code, zip_rows in by_zip.items():
        city = Counter(row.get("city") for row in zip_rows if row.get("city")).most_common(1)
        state = Counter(row.get("state") for row in zip_rows if row.get("state")).most_common(1)
        populations = [row.get("population") for row in zip_rows if isinstance(row.get("population"), int)]
        others = [row for row in state_rows if str(row.get("zip_code")) != zip_code]

        metrics: list[dict] = []
        for spec in metric_specs:
            local_value, local_n = _metric_on_rows(
                zip_rows,
                spec["field"],
                spec["method"],
                spec.get("positive_values"),
                spec.get("focus_value"),
            )
            base_value, base_n = _metric_on_rows(
                others,
                spec["field"],
                spec["method"],
                spec.get("positive_values"),
                spec.get("focus_value"),
            )
            if local_value is None or base_value is None:
                continue
            if isinstance(local_value, dict):
                # compare top level by max absolute share delta
                for key, share in local_value.items():
                    baseline_share = (base_value or {}).get(key, 0.0)
                    delta = share - baseline_share
                    if not _keep("share", share, baseline_share) and local_n >= MIN_N:
                        continue
                    metrics.append({
                        "metric": f"{spec['name']}:{key}",
                        "label": f"{spec['label']}={key}",
                        "kind": spec["kind"],
                        "method": "share",
                        "value": share,
                        "baseline": baseline_share,
                        "delta": delta,
                        "n": local_n,
                        "thin_sample": local_n < MIN_N,
                        "gap_score": _gap_score("share", share, baseline_share, local_n),
                        "unit": "share",
                    })
                continue

            delta = float(local_value) - float(base_value)
            metrics.append({
                "metric": spec["name"],
                "label": spec["label"],
                "kind": spec["kind"],
                "method": spec["method"],
                "value": float(local_value),
                "baseline": float(base_value),
                "delta": delta,
                "n": local_n,
                "thin_sample": local_n < MIN_N,
                "gap_score": _gap_score(spec["method"], float(local_value), float(base_value), local_n),
                "unit": "number" if spec["method"] == "mean" else "share",
            })

        patterns_out: list[dict] = []
        for pattern in catalog.get("patterns") or []:
            filters = pattern.get("filters") or {}
            local_filtered = [row for row in zip_rows if _matches(row, filters)]
            other_filtered = [row for row in others if _matches(row, filters)]
            pattern_metrics = []
            for metric in pattern.get("metrics") or []:
                field = metric.get("field") or "high_risk"
                method = metric.get("method") or "share"
                local_value, local_n = _metric_on_rows(
                    local_filtered,
                    field,
                    method,
                    metric.get("positive_values"),
                    metric.get("focus_value"),
                )
                base_value, _ = _metric_on_rows(
                    other_filtered,
                    field,
                    method,
                    metric.get("positive_values"),
                    metric.get("focus_value"),
                )
                # If the segment is rare elsewhere, fall back to unfiltered rest-of-state.
                if base_value is None:
                    base_value, _ = _metric_on_rows(
                        others,
                        field,
                        method,
                        metric.get("positive_values"),
                        metric.get("focus_value"),
                    )
                if local_value is None or base_value is None or isinstance(local_value, dict):
                    continue
                pattern_metrics.append({
                    "metric": metric.get("metric") or field,
                    "value": float(local_value),
                    "baseline": float(base_value),
                    "delta": float(local_value) - float(base_value),
                    "n": local_n,
                    "method": method,
                })
            if not pattern_metrics:
                continue
            top = max(pattern_metrics, key=lambda item: abs(item["delta"]) * item["n"])
            patterns_out.append({
                "pattern_id": pattern["id"],
                "description": pattern.get("description") or pattern["id"],
                "n": len(local_filtered),
                "thin_sample": len(local_filtered) < MIN_N,
                "gap_score": abs(top["delta"]) * top["n"],
                "metrics": pattern_metrics,
            })

        risk_rate = next(
            (m for m in metrics if m["metric"] == "risk_rate" and isinstance(m.get("value"), (int, float))),
            None,
        )
        risk_mean = next(
            (m for m in metrics if m["metric"] == "risk_score_mean" and isinstance(m.get("value"), (int, float))),
            None,
        )
        primary_risk = risk_rate or risk_mean
        # Friction table: outcomes + drivers; prefer non-thin, then higher gap.
        ranked = sorted(
            [m for m in metrics if not isinstance(m.get("value"), dict)],
            key=lambda item: (
                1 if item.get("thin_sample") else 0,
                0 if item.get("kind") == "outcome" else 1,
                -(item.get("gap_score") or 0.0),
            ),
        )
        patterns_out.sort(key=lambda item: item.get("gap_score") or 0.0, reverse=True)
        outcome_gap = primary_risk["gap_score"] if primary_risk else 0.0
        driver_gap = next(
            (m["gap_score"] for m in ranked if m.get("kind") == "driver"),
            0.0,
        )
        profile = {
            "zip_code": zip_code,
            "city": city[0][0] if city else None,
            "state": state[0][0] if state else None,
            "population": max(populations) if populations else None,
            "customers": len(zip_rows),
            "thin_sample": len(zip_rows) < MIN_N,
            "risk_rate": risk_rate["value"] if risk_rate else None,
            "risk_baseline": risk_rate["baseline"] if risk_rate else None,
            "risk_score_mean": risk_mean["value"] if risk_mean else None,
            "risk_score_baseline": risk_mean["baseline"] if risk_mean else None,
            # Legacy aliases used by older UI/graph payloads (now predictive risk share).
            "churn_rate": risk_rate["value"] if risk_rate else None,
            "churn_baseline": risk_rate["baseline"] if risk_rate else None,
            "metrics": metrics,
            "patterns": patterns_out,
            "top_gaps": ranked[:8],
            "gap_score": max(outcome_gap, driver_gap),
        }
        enriched = enrich_profile_with_customers(profile, zip_rows)
        # Honeycomb uses risk_rate; never leave it null when we know high-risk counts.
        if enriched.get("risk_rate") is None:
            n = int(enriched.get("customers") or len(zip_rows) or 0)
            hr = int(enriched.get("high_risk_customers") or 0)
            if n > 0:
                rate = round(hr / n, 4)
                enriched["risk_rate"] = rate
                enriched["churn_rate"] = rate
        enriched = enrich_profile_with_domain_metrics(enriched, zip_rows)
        # Rules-based upsells + campaign drafts (AI polish is on-demand per zip).
        profiles.append(enrich_profile_with_behaviour(enriched, zip_rows, use_ai_campaigns=False))

    profiles.sort(key=lambda item: item.get("gap_score") or 0.0, reverse=True)
    return profiles
