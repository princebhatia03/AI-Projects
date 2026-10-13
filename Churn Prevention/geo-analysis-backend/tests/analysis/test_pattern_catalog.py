import pytest

from app.analysis.pattern_catalog import default_catalog, validate_catalog


def test_default_catalog_valid():
    catalog = validate_catalog(default_catalog(), columns=[
        "high_risk", "low_satisfaction", "satisfaction_score", "churn_score", "unlimited_data",
        "internet_service", "online_security", "premium_tech_support", "contract",
        "internet_type", "monthly_charge", "avg_monthly_gb",
        "total_extra_data_charges", "tenure_months", "phone_service", "zip_code",
        "dependents", "multiple_lines",
    ])
    assert catalog["place_key"] == "zip_code"
    assert catalog["patterns"]
    outcome_metrics = {item.get("metric") for item in catalog["outcomes"]}
    assert "risk_rate" in outcome_metrics
    assert "churn_rate" not in outcome_metrics
    assert "churn_category" not in {d["field"] for d in catalog["drivers"]}


def test_rejects_bad_place_key():
    catalog = default_catalog()
    catalog["place_key"] = "city"
    with pytest.raises(ValueError):
        validate_catalog(catalog)


def test_llm_blob_metrics_are_coerced_to_string_names():
    """Models sometimes put by_zip aggregates in metric — honeycomb needs risk_rate."""
    catalog = validate_catalog({
        "place_key": "zip_code",
        "baseline": {"overall_high_risk_share": 1.0},
        "source": "model",
        "outcomes": [
            {
                "field": "high_risk",
                "method": "share",
                "focus_value": "Yes",
                "metric": {"by_zip_code": {"56080": 1.0}},
            },
            {
                "field": "churn_score",
                "method": "distribution",
                "metric": {"by_zip_code": {"56080": {"mean": 90}}},
            },
        ],
        "drivers": [],
        "patterns": [],
    }, columns=["high_risk", "churn_score", "zip_code"])
    assert catalog["baseline"] == "rest_of_state"
    metrics = {item["metric"] for item in catalog["outcomes"]}
    assert "risk_rate" in metrics
    assert "risk_score_mean" in metrics
    risk = next(item for item in catalog["outcomes"] if item["metric"] == "risk_rate")
    assert risk["field"] == "high_risk"
    assert risk["method"] == "share"
    assert risk["positive_values"] == ["Yes"]
    assert all(isinstance(item["metric"], str) for item in catalog["outcomes"])
    # Canonical definitions are pinned — model cannot redefine risk_rate.
    assert risk["positive_values"] == ["Yes"]
    assert catalog["outcomes"][0]["metric"] == "risk_rate"
    assert catalog["outcomes"][1]["metric"] == "risk_score_mean"


def test_blob_catalog_still_yields_numeric_risk_rates():
    from app.analysis.loader import as_active_customer
    from app.analysis.pattern_catalog import assert_profiles_have_risk_rates
    from app.analysis.pincode_aggregate import aggregate_by_pincode

    catalog = validate_catalog({
        "place_key": "zip_code",
        "baseline": {"overall": 1},
        "source": "model",
        "outcomes": [{
            "field": "high_risk",
            "method": "share",
            "metric": {"by_zip_code": {"90001": 0.5}},
        }],
        "drivers": [],
        "patterns": [],
    }, columns=["high_risk", "churn_score", "zip_code"])
    rows = [
        as_active_customer({
            "customer_id": "a1",
            "zip_code": "90001",
            "city": "LA",
            "state": "CA",
            "churn_score": 80,
            "satisfaction_score": 2,
            "phone_service": "Yes",
            "internet_service": "Yes",
            "monthly_charge": 70,
            "contract": "Month-to-Month",
        }),
        as_active_customer({
            "customer_id": "a2",
            "zip_code": "90001",
            "city": "LA",
            "state": "CA",
            "churn_score": 20,
            "satisfaction_score": 5,
            "phone_service": "Yes",
            "internet_service": "Yes",
            "monthly_charge": 40,
            "contract": "Two Year",
        }),
    ]
    profiles = aggregate_by_pincode(rows, catalog)
    assert_profiles_have_risk_rates(profiles)
    assert profiles[0]["risk_rate"] == 0.5
