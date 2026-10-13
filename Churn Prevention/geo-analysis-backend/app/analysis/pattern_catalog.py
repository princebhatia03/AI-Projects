"""Risk pattern catalog: schema, validation, defaults, optional LLM.

Framing: Dataset rows are active subscribers. Catalogs predict what is
going wrong in a pincode (risk / dissatisfaction / service gaps), not who left.
"""

from __future__ import annotations

import json
from typing import Any

from app import config


DEFAULT_CATALOG = {
    "place_key": "zip_code",
    "baseline": "rest_of_state",
    "source": "default",
    "outcomes": [
        {
            "field": "high_risk",
            "positive_values": ["Yes"],
            "metric": "risk_rate",
            "method": "share",
            "reason": "Share of customers above the predictive risk threshold",
        },
        {
            "field": "churn_score",
            "metric": "risk_score_mean",
            "method": "mean",
            "reason": "Mean predictive leave-risk score among active users",
        },
        {
            "field": "satisfaction_score",
            "metric": "satisfaction_mean",
            "method": "mean",
            "reason": "Dissatisfaction signal (lower is worse)",
        },
        {
            "field": "low_satisfaction",
            "positive_values": ["Yes"],
            "metric": "low_satisfaction_rate",
            "method": "share",
            "reason": "Share with critically low satisfaction",
        },
    ],
    "drivers": [
        {"field": "unlimited_data", "method": "share", "focus_value": "Yes", "reason": "Unlimited adoption"},
        {"field": "internet_service", "method": "share", "focus_value": "Yes", "reason": "Internet penetration"},
        {"field": "online_security", "method": "share", "focus_value": "Yes", "reason": "Security add-on"},
        {"field": "premium_tech_support", "method": "share", "focus_value": "Yes", "reason": "Support add-on"},
        {"field": "contract", "method": "distribution", "reason": "Contract mix"},
        {"field": "internet_type", "method": "distribution", "reason": "Access technology mix"},
        {"field": "monthly_charge", "method": "mean", "reason": "Price pressure"},
        {"field": "avg_monthly_gb", "method": "mean", "reason": "Usage intensity"},
        {"field": "total_extra_data_charges", "method": "mean", "reason": "Overage fees"},
        {"field": "tenure_months", "method": "mean", "reason": "Tenure"},
        {"field": "dependents", "method": "share", "focus_value": "Yes", "reason": "Household dependents"},
        {"field": "multiple_lines", "method": "share", "focus_value": "Yes", "reason": "Multi-line adoption"},
    ],
    "patterns": [
        {
            "id": "heavy_usage_no_unlimited",
            "description": "Heavy internet users without unlimited data — overage risk",
            "filters": {"internet_service": "Yes", "unlimited_data": "No"},
            "metrics": [
                {"field": "avg_monthly_gb", "method": "mean"},
                {"field": "total_extra_data_charges", "method": "mean"},
                {"field": "churn_score", "method": "mean", "metric": "risk_score_mean"},
                {"field": "high_risk", "method": "share", "positive_values": ["Yes"], "metric": "risk_rate"},
            ],
        },
        {
            "id": "phone_only_no_internet",
            "description": "Phone-only households missing home internet — upsell gap",
            "filters": {"phone_service": "Yes", "internet_service": "No"},
            "metrics": [
                {"field": "churn_score", "method": "mean", "metric": "risk_score_mean"},
                {"field": "high_risk", "method": "share", "positive_values": ["Yes"], "metric": "risk_rate"},
            ],
        },
        {
            "id": "contract_month_to_month",
            "description": "Month-to-month contracts — elevated exit flexibility risk",
            "filters": {"contract": "Month-to-Month"},
            "metrics": [
                {"field": "satisfaction_score", "method": "mean"},
                {"field": "churn_score", "method": "mean", "metric": "risk_score_mean"},
                {"field": "high_risk", "method": "share", "positive_values": ["Yes"], "metric": "risk_rate"},
            ],
        },
        {
            "id": "high_churn_score",
            "description": "Customers already flagged high predictive risk",
            "filters": {"high_risk": "Yes"},
            "metrics": [
                {"field": "satisfaction_score", "method": "mean"},
                {"field": "monthly_charge", "method": "mean"},
                {"field": "tenure_months", "method": "mean"},
            ],
        },
        {
            "id": "low_satisfaction",
            "description": "Critically low satisfaction among active users",
            "filters": {"low_satisfaction": "Yes"},
            "metrics": [
                {"field": "churn_score", "method": "mean", "metric": "risk_score_mean"},
                {"field": "monthly_charge", "method": "mean"},
            ],
        },
        {
            "id": "no_security_addon",
            "description": "Internet users without online security",
            "filters": {"internet_service": "Yes", "online_security": "No"},
            "metrics": [
                {"field": "churn_score", "method": "mean", "metric": "risk_score_mean"},
                {"field": "high_risk", "method": "share", "positive_values": ["Yes"], "metric": "risk_rate"},
            ],
        },
        {
            "id": "no_tech_support",
            "description": "Internet users without premium tech support",
            "filters": {"internet_service": "Yes", "premium_tech_support": "No"},
            "metrics": [
                {"field": "churn_score", "method": "mean", "metric": "risk_score_mean"},
                {"field": "satisfaction_score", "method": "mean"},
            ],
        },
        {
            "id": "price_sensitivity",
            "description": "High monthly charges with low satisfaction — price pressure",
            "filters": {"low_satisfaction": "Yes"},
            "metrics": [
                {"field": "monthly_charge", "method": "mean"},
                {"field": "churn_score", "method": "mean", "metric": "risk_score_mean"},
            ],
        },
    ],
    "ignore": [
        "customer_id",
        "gender",
        "latitude",
        "longitude",
        "lat_long",
        "location_id",
        "count",
        "customer_status",
        "churn_category",
        "churn_reason",
    ],
}


_FIELD_METRIC_DEFAULTS = {
    "high_risk": "risk_rate",
    "churn_score": "risk_score_mean",
    "satisfaction_score": "satisfaction_mean",
    "low_satisfaction": "low_satisfaction_rate",
}


def _normalize_metric_name(item: dict[str, Any]) -> str:
    """LLM catalogs sometimes put pre-aggregated blobs in ``metric`` — force a string id."""
    metric = item.get("metric")
    if isinstance(metric, str) and metric.strip():
        return metric.strip()
    field = str(item.get("field") or "").strip()
    return _FIELD_METRIC_DEFAULTS.get(field, field or "metric")


def _normalize_outcome_or_driver(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    out["metric"] = _normalize_metric_name(item)
    method = out.get("method")
    # Share of high_risk needs Yes/No positives; models often omit them.
    if out.get("field") == "high_risk" and method in {"share", "rate", "ratio"}:
        if not out.get("positive_values") and not out.get("focus_value"):
            out["positive_values"] = ["Yes"]
        elif out.get("focus_value") and not out.get("positive_values"):
            out["positive_values"] = [out["focus_value"]]
    # Distribution of churn_score cannot become risk_rate; coerce to mean for score.
    if out.get("field") == "churn_score" and method == "distribution":
        out["method"] = "mean"
        if out["metric"] == "churn_score":
            out["metric"] = "risk_score_mean"
    return out


def validate_catalog(catalog: dict[str, Any], columns: list[str] | None = None) -> dict[str, Any]:
    if not isinstance(catalog, dict):
        raise ValueError("catalog must be an object")
    place_key = catalog.get("place_key") or "zip_code"
    if place_key != "zip_code":
        raise ValueError("place_key must be zip_code")
    outcomes = [_normalize_outcome_or_driver(item) for item in (catalog.get("outcomes") or [])]
    drivers = [_normalize_outcome_or_driver(item) for item in (catalog.get("drivers") or [])]
    patterns = catalog.get("patterns") or []
    if not outcomes and not drivers and not patterns:
        raise ValueError("catalog needs outcomes, drivers, or patterns")

    known = set(columns or [])
    allowed_synthetic = {"risk_rate", "risk_score_mean", "high_risk", "low_satisfaction"}
    for item in list(outcomes) + list(drivers):
        field = item.get("field")
        if not field:
            raise ValueError("each outcome/driver needs a field")
        if known and field not in known and field not in allowed_synthetic:
            raise ValueError(f"unknown field in catalog: {field}")
        method = item.get("method")
        if method not in {"share", "mean", "distribution", "top_values", "rate", "ratio"}:
            raise ValueError(f"unsupported method: {method}")
        if not isinstance(item.get("metric"), str):
            raise ValueError("each outcome/driver metric must be a short string name")

    # Always pin honeycomb-critical outcomes from the default catalog so an LLM
    # cannot replace risk_rate with blobs or drop it entirely.
    outcomes = _pin_required_risk_outcomes(outcomes)

    for pattern in patterns:
        if not pattern.get("id"):
            raise ValueError("each pattern needs an id")
        for metric in pattern.get("metrics") or []:
            method = metric.get("method")
            if method not in {"share", "mean", "distribution", "top_values", "rate", "ratio"}:
                raise ValueError(f"unsupported pattern method: {method}")

    baseline = catalog.get("baseline")
    if not isinstance(baseline, str) or not baseline.strip():
        baseline = "rest_of_state"

    cleaned = {
        "place_key": "zip_code",
        "baseline": baseline,
        "source": catalog.get("source") or "model",
        "outcomes": outcomes,
        "drivers": drivers,
        "patterns": patterns,
        "ignore": list(catalog.get("ignore") or DEFAULT_CATALOG["ignore"]),
    }
    return cleaned


def default_catalog() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_CATALOG))


def _pin_required_risk_outcomes(outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Force canonical risk_rate / risk_score_mean definitions (model may not override)."""
    required = {
        item["metric"]: dict(item)
        for item in DEFAULT_CATALOG["outcomes"]
        if item.get("metric") in {"risk_rate", "risk_score_mean"}
    }
    kept = [
        item for item in outcomes
        if item.get("metric") not in required
    ]
    return [required["risk_rate"], required["risk_score_mean"], *kept]


def assert_profiles_have_risk_rates(profiles: list[dict[str, Any]]) -> None:
    """Fail the pipeline if honeycomb risk % would render as 0 from nulls."""
    missing = [
        str(p.get("zip_code"))
        for p in profiles
        if not isinstance(p.get("risk_rate"), (int, float))
    ]
    if missing:
        sample = ", ".join(missing[:8])
        more = f" (+{len(missing) - 8} more)" if len(missing) > 8 else ""
        raise ValueError(
            f"{len(missing)} pincode profiles missing numeric risk_rate "
            f"(honeycomb would show 0%). Examples: {sample}{more}"
        )


def catalog_from_model(headers: list[str], sample_rows: list[dict]) -> dict | None:
    if not config.llm_ready():
        return None
    config.apply_litellm_env()
    try:
        from litellm import completion
    except Exception:
        return None

    prompt = {
        "role": "user",
        "content": (
            "You design a PREDICTIVE risk pattern catalog for active telco subscribers by pincode.\n"
            "Assume NO customer has churned yet. Do not use past churn labels or 'why people left'.\n"
            "Focus on predictive risk (churn_score, high_risk), dissatisfaction, and service gaps "
            "so sales can assign preventive offers.\n"
            "Return ONLY JSON with keys: place_key (must be zip_code), baseline, outcomes, drivers, patterns, ignore.\n"
            "outcomes/drivers items: field, method (share|mean|distribution|top_values), optional focus_value, "
            "positive_values, metric (SHORT STRING name only, e.g. risk_rate — NEVER put numbers or by_zip blobs in metric), reason.\n"
            "Always include outcome metric=risk_rate on field=high_risk method=share positive_values=[Yes].\n"
            "Always include outcome metric=risk_score_mean on field=churn_score method=mean.\n"
            "patterns items: id, description, filters (object), metrics (list like drivers).\n"
            "Ignore customer_status, churn_category, churn_reason.\n"
            "Use only these columns: "
            + ", ".join(headers)
            + "\nSample rows:\n"
            + json.dumps(sample_rows[:8])
        ),
    }
    try:
        response = completion(
            model=config.litellm_model(),
            messages=[
                {"role": "system", "content": "Return valid JSON only. No markdown."},
                prompt,
            ],
            temperature=0.1,
            **config.litellm_call_kwargs(),
        )
        text = response.choices[0].message.content or ""
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(text)
        parsed["source"] = "model"
        return validate_catalog(parsed, headers)
    except Exception:
        return None


def resolve_catalog(headers: list[str], sample_rows: list[dict]) -> dict:
    model_catalog = catalog_from_model(headers, sample_rows)
    if model_catalog:
        return model_catalog
    catalog = default_catalog()
    return validate_catalog(catalog, headers)
