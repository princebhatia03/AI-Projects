"""Churn × domain metrics for Demographics, Location, Population, Services, Status."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app import config

# Fields mapped to the five DataSet source tables (after join / rename).
DOMAIN_FIELDS: dict[str, list[str]] = {
    "Demographics": [
        "age",
        "under_30",
        "senior_citizen",
        "married",
        "dependents",
        "number_of_dependents",
    ],
    "Location": [
        "city",
        "state",
        "zip_code",
    ],
    "Population": [
        "population",
    ],
    "Services": [
        "phone_service",
        "multiple_lines",
        "internet_service",
        "internet_type",
        "avg_monthly_gb",
        "unlimited_data",
        "online_security",
        "premium_tech_support",
        "contract",
        "monthly_charge",
        "total_extra_data_charges",
        "tenure_months",
        "offer",
    ],
    "Status": [
        "satisfaction_score",
        "low_satisfaction",
        "churn_score",
        "high_risk",
        "cltv",
        "customer_status",
    ],
}

# Segment dimensions used for Churn × domain slice rates.
DOMAIN_SEGMENTS: dict[str, list[dict[str, Any]]] = {
    "Demographics": [
        {"field": "senior_citizen", "value": "Yes", "label": "Senior citizen"},
        {"field": "under_30", "value": "Yes", "label": "Under 30"},
        {"field": "married", "value": "Yes", "label": "Married"},
        {"field": "dependents", "value": "Yes", "label": "Has dependents"},
    ],
    "Location": [
        # city/zip are place keys — segment by thin vs not is less useful; use state presence.
        {"field": "state", "value": None, "label": "In-state cohort", "mode": "present"},
    ],
    "Population": [
        {"field": "population", "value": None, "label": "Dense zip (pop ≥ median)", "mode": "population_high"},
        {"field": "population", "value": None, "label": "Sparse zip (pop < median)", "mode": "population_low"},
    ],
    "Services": [
        {"field": "contract", "value": "Month-to-Month", "label": "Month-to-month"},
        {"field": "internet_service", "value": "Yes", "label": "Has internet"},
        {"field": "phone_service", "value": "Yes", "label": "Has phone"},
        {"field": "unlimited_data", "value": "No", "label": "Metered data"},
        {"field": "online_security", "value": "No", "label": "No security addon"},
        {"field": "premium_tech_support", "value": "No", "label": "No premium support"},
        {"field": "multiple_lines", "value": "Yes", "label": "Multiple lines"},
    ],
    "Status": [
        {"field": "high_risk", "value": "Yes", "label": "High risk score"},
        {"field": "low_satisfaction", "value": "Yes", "label": "Low satisfaction"},
        {"field": "customer_status", "value": "Active", "label": "Active status"},
    ],
}


def _is_high_risk(row: dict) -> bool:
    if row.get("high_risk") == "Yes":
        return True
    score = row.get("churn_score")
    return isinstance(score, (int, float)) and not isinstance(score, bool) and score >= config.HIGH_RISK_SCORE


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _risk_share(rows: list[dict]) -> float | None:
    if not rows:
        return None
    return sum(1 for row in rows if _is_high_risk(row)) / len(rows)


def _score_mean(rows: list[dict]) -> float | None:
    nums = [
        float(row["churn_score"])
        for row in rows
        if isinstance(row.get("churn_score"), (int, float)) and not isinstance(row.get("churn_score"), bool)
    ]
    return _mean(nums)


def _sat_mean(rows: list[dict]) -> float | None:
    nums = [
        float(row["satisfaction_score"])
        for row in rows
        if isinstance(row.get("satisfaction_score"), (int, float))
        and not isinstance(row.get("satisfaction_score"), bool)
    ]
    return _mean(nums)


def _population_median(rows: list[dict]) -> float | None:
    pops = [
        float(row["population"])
        for row in rows
        if isinstance(row.get("population"), (int, float)) and not isinstance(row.get("population"), bool)
    ]
    if not pops:
        return None
    pops.sort()
    mid = len(pops) // 2
    if len(pops) % 2:
        return pops[mid]
    return (pops[mid - 1] + pops[mid]) / 2


def _segment_rows(rows: list[dict], spec: dict[str, Any], *, pop_median: float | None) -> list[dict]:
    mode = spec.get("mode")
    field = spec["field"]
    if mode == "present":
        return [row for row in rows if row.get(field) not in (None, "")]
    if mode == "population_high":
        if pop_median is None:
            return []
        return [
            row
            for row in rows
            if isinstance(row.get("population"), (int, float)) and float(row["population"]) >= pop_median
        ]
    if mode == "population_low":
        if pop_median is None:
            return []
        return [
            row
            for row in rows
            if isinstance(row.get("population"), (int, float)) and float(row["population"]) < pop_median
        ]
    return [row for row in rows if row.get(field) == spec.get("value")]


def _top_value_risk(rows: list[dict], field: str, top_n: int = 4) -> list[dict]:
    """Churn risk share for the most common categorical values of a field."""
    present = [row for row in rows if row.get(field) not in (None, "")]
    if not present:
        return []
    counts = Counter(str(row.get(field)) for row in present)
    out: list[dict] = []
    for value, count in counts.most_common(top_n):
        group = [row for row in present if str(row.get(field)) == value]
        out.append({
            "segment": f"{field}={value}",
            "label": value,
            "field": field,
            "customers": count,
            "risk_rate": _risk_share(group),
            "churn_score_mean": _score_mean(group),
        })
    return out


def compute_domain_churn_metrics(rows: list[dict]) -> list[dict[str, Any]]:
    """Build Churn × {Demographics, Location, Population, Services, Status} metrics."""
    if not rows:
        return []

    overall_risk = _risk_share(rows)
    overall_score = _score_mean(rows)
    overall_sat = _sat_mean(rows)
    pop_median = _population_median(rows)

    domains: list[dict[str, Any]] = []
    for domain, fields in DOMAIN_FIELDS.items():
        available = [field for field in fields if any(row.get(field) not in (None, "") for row in rows)]
        segments_out: list[dict] = []
        for spec in DOMAIN_SEGMENTS.get(domain, []):
            group = _segment_rows(rows, spec, pop_median=pop_median)
            if len(group) < 1:
                continue
            segments_out.append({
                "segment": spec["label"],
                "label": spec["label"],
                "field": spec["field"],
                "customers": len(group),
                "risk_rate": _risk_share(group),
                "churn_score_mean": _score_mean(group),
                "satisfaction_mean": _sat_mean(group),
                "delta_vs_overall": (
                    None
                    if _risk_share(group) is None or overall_risk is None
                    else round(float(_risk_share(group)) - float(overall_risk), 4)
                ),
            })

        # Extra categorical cuts for richer Services / Demographics views.
        value_cuts: list[dict] = []
        if domain == "Services":
            for field in ("contract", "internet_type"):
                value_cuts.extend(_top_value_risk(rows, field, top_n=3))
        if domain == "Demographics":
            # Age bands as behavioural proxies.
            bands = [
                ("age≤30", lambda r: isinstance(r.get("age"), (int, float)) and r["age"] <= 30),
                ("age 31–55", lambda r: isinstance(r.get("age"), (int, float)) and 31 <= r["age"] <= 55),
                ("age≥56", lambda r: isinstance(r.get("age"), (int, float)) and r["age"] >= 56),
            ]
            for label, pred in bands:
                group = [row for row in rows if pred(row)]
                if not group:
                    continue
                value_cuts.append({
                    "segment": label,
                    "label": label,
                    "field": "age",
                    "customers": len(group),
                    "risk_rate": _risk_share(group),
                    "churn_score_mean": _score_mean(group),
                })

        # Domain "pressure" score: how much this domain's segments deviate from overall risk.
        deltas = [
            abs(float(item["delta_vs_overall"]))
            for item in segments_out
            if item.get("delta_vs_overall") is not None
        ]
        domain_pressure = round(_mean(deltas) or 0.0, 4)

        domains.append({
            "domain": domain,
            "source_file": f"Telco_customer_churn_{domain.lower()}.csv",
            "fields": available,
            "customers": len(rows),
            "risk_rate": overall_risk,
            "churn_score_mean": overall_score,
            "satisfaction_mean": overall_sat if domain == "Status" else None,
            "domain_pressure": domain_pressure,
            "segments": sorted(
                segments_out,
                key=lambda item: abs(item.get("delta_vs_overall") or 0),
                reverse=True,
            ),
            "value_cuts": value_cuts,
            "headline": _domain_headline(domain, segments_out, overall_risk),
        })

    domains.sort(key=lambda item: item.get("domain_pressure") or 0, reverse=True)
    return domains


def _domain_headline(domain: str, segments: list[dict], overall_risk: float | None) -> str:
    if not segments:
        return f"{domain}: no segment lift vs overall risk"
    top = max(segments, key=lambda item: abs(item.get("delta_vs_overall") or 0))
    delta = top.get("delta_vs_overall")
    if delta is None or overall_risk is None:
        return f"{domain}: {top['label']}"
    if abs(delta) < 0.005:
        return f"{domain}: {top['label']} in line with overall risk ({overall_risk:.0%})"
    direction = "higher" if delta > 0 else "lower"
    return (
        f"{domain}: {top['label']} shows {direction} churn risk "
        f"({delta:+.0%} vs overall {overall_risk:.0%})"
    )


def enrich_profile_with_domain_metrics(profile: dict, zip_rows: list[dict]) -> dict:
    profile["churn_by_domain"] = compute_domain_churn_metrics(zip_rows)
    return profile
