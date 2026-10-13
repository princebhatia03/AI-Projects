"""Telecom CLV and customer-card helpers."""

from app.analysis.business_impact import (
    _contract_monthly_churn,
    _monthly_discount_rate,
    customer_clv_eur,
    enrich_profile_with_customers,
)


def test_customer_clv_uses_telecom_discounted_formula():
    row = {
        "monthly_charge": 100.0,
        "contract": "Month-to-month",
        "cltv": 99999,  # opaque dataset score must not override the formula
    }
    margin = 0.60
    churn = _contract_monthly_churn("Month-to-month")
    discount = _monthly_discount_rate()
    expected = round((100.0 * margin) / (churn + discount), 2)
    assert customer_clv_eur(row) == expected


def test_longer_contracts_have_higher_clv():
    base = {"monthly_charge": 80.0}
    m2m = customer_clv_eur({**base, "contract": "Month-to-month"})
    one = customer_clv_eur({**base, "contract": "One year"})
    two = customer_clv_eur({**base, "contract": "Two year"})
    assert m2m < one < two


def test_zero_arpu_is_zero_clv():
    assert customer_clv_eur({"monthly_charge": 0, "contract": "Two year"}) == 0.0


def test_expected_loss_applies_individual_churn_on_top_of_clv():
    rows = [
        {
            "customer_id": "c1",
            "monthly_charge": 100.0,
            "contract": "Two year",
            "churn_score": 80,
            "phone_service": "Yes",
            "internet_service": "Yes",
            "high_risk": "Yes",
            "tenure_months": 12,
            "satisfaction_score": 2,
        }
    ]
    profile = enrich_profile_with_customers({}, rows)
    card = profile["customers_detail"][0]
    assert card["clv_eur"] == customer_clv_eur(rows[0])
    assert profile["expected_loss_eur"] == round(
        card["clv_eur"] * card["churn_probability"],
        2,
    )
