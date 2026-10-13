from app.analysis.behaviour_actions import (
    enrich_profile_with_behaviour,
    potential_upsell_gain_eur,
    upsell_addressable_clv_eur,
)


def test_upsell_clv_is_unique_across_signals():
    rows = [
        {
            "internet_service": "Yes",
            "online_security": "No",
            "premium_tech_support": "No",
            "phone_service": "Yes",
            "unlimited_data": "Yes",
            "dependents": "No",
            "multiple_lines": "No",
            "contract": "One Year",
            "monthly_charge": 80.0,
            "tenure_months": 24,
            "cltv": 2000.0,
            "churn_score": 40,
            "satisfaction_score": 4,
        },
        {
            "internet_service": "Yes",
            "online_security": "No",
            "premium_tech_support": "Yes",
            "phone_service": "Yes",
            "unlimited_data": "Yes",
            "dependents": "No",
            "multiple_lines": "No",
            "contract": "One Year",
            "monthly_charge": 60.0,
            "tenure_months": 12,
            "cltv": 1000.0,
            "churn_score": 30,
            "satisfaction_score": 4,
        },
    ]
    unique = upsell_addressable_clv_eur(rows)
    profile = enrich_profile_with_behaviour(
        {"zip_code": "99999", "city": "Test"},
        rows,
        use_ai_campaigns=False,
    )
    assert profile["upsell_clv_eur"] == unique
    assert unique > 0
    # Per-signal addressable can exceed unique when one customer matches multiple rules.
    signal_sum = sum(float(item["addressable_clv_eur"]) for item in profile["upsell_opportunities"])
    assert unique <= signal_sum
    assert profile["upsell_potential_gain_eur"] >= 0
    assert profile["upsell_potential_gain_period"] == "year"
    assert profile["upsell_yearly_eur"] >= profile["upsell_potential_gain_eur"]
    for item in profile["upsell_opportunities"]:
        assert "yearly_uplift_eur" in item
        assert "yearly_upsell_eur" in item
        assert item["potential_gain_period"] == "year"
        assert "monthly_uplift_eur" not in item


def test_upsell_and_campaigns_explain_the_data_found():
    rows = [
        {
            "internet_service": "Yes",
            "online_security": "No",
            "premium_tech_support": "Yes",
            "phone_service": "Yes",
            "unlimited_data": "No",
            "dependents": "No",
            "multiple_lines": "No",
            "contract": "Month-to-month",
            "monthly_charge": 90.0,
            "tenure_months": 4,
            "cltv": 2000.0,
            "churn_score": 82,
            "high_risk": "Yes",
            "satisfaction_score": 2,
            "avg_monthly_gb": 60,
            "low_satisfaction": "Yes",
        },
        {
            "internet_service": "Yes",
            "online_security": "Yes",
            "premium_tech_support": "Yes",
            "phone_service": "Yes",
            "unlimited_data": "Yes",
            "dependents": "No",
            "multiple_lines": "No",
            "contract": "Two year",
            "monthly_charge": 40.0,
            "tenure_months": 30,
            "cltv": 1500.0,
            "churn_score": 20,
            "high_risk": "No",
            "satisfaction_score": 5,
            "avg_monthly_gb": 10,
        },
    ]
    profile = enrich_profile_with_behaviour(
        {"zip_code": "10115", "city": "Berlin"},
        rows,
        use_ai_campaigns=False,
    )
    unlimited = next(item for item in profile["upsell_opportunities"] if item["signal"] == "heavy_usage_no_unlimited")
    assert "60 GB/month" in unlimited["why"]
    assert unlimited["evidence"]
    assert "no unlimited data" in unlimited["evidence"][0]
    security = next(item for item in profile["upsell_opportunities"] if item["signal"] == "no_security_addon")
    assert "no online security" in security["why"]

    retention = next(item for item in profile["suggested_campaigns"] if item["campaign_type"] == "retention")
    assert "Shown because" in retention["why"]
    assert "82/100" in retention["why"]
    assert retention["churn_risk"]["avg_churn_score"] == 82
    upsell_campaign = next(item for item in profile["suggested_campaigns"] if item["campaign_type"] == "upsell")
    assert upsell_campaign["why"]
    assert upsell_campaign["evidence"]


def test_potential_upsell_gain_is_yearly():
    # 2 customers × €60/year × 0.6 margin × 0.20 take-rate = €14.40
    assert potential_upsell_gain_eur(
        customers=2,
        yearly_uplift_eur=60.0,
        addressable_clv_eur=10_000.0,
    ) == 14.4
