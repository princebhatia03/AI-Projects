"""Per-customer suggested offer lists for high-risk triggers."""

from app.analysis.business_impact import build_customer_card, enrich_profile_with_customers
from app.analysis.customer_campaigns import build_suggested_offers
from app.analysis.offers import match_offer, match_offers


def _menu():
    return [
        {
            "offer_id": "OFF_PREVENT",
            "name": "Preventive loyalty credit",
            "description": "Proactive credit for high risk.",
            "addresses_patterns": ["high_churn_score", "high_risk"],
            "channel": "care",
            "priority": 1,
        },
        {
            "offer_id": "OFF_CONTRACT",
            "name": "Annual contract perk",
            "description": "Longer contract incentive.",
            "addresses_patterns": ["contract_month_to_month", "contract"],
            "channel": "retail",
            "priority": 2,
        },
        {
            "offer_id": "OFF_SUPPORT",
            "name": "Premium tech support",
            "description": "Support bundle.",
            "addresses_patterns": ["no_tech_support", "low_satisfaction"],
            "channel": "care",
            "priority": 3,
        },
        {
            "offer_id": "OFF_UNRELATED",
            "name": "Fiber",
            "description": "Fiber upgrade.",
            "addresses_patterns": ["fiber", "internet_type"],
            "channel": "field",
            "priority": 2,
        },
    ]


def test_match_offers_returns_ranked_list():
    matches = match_offers(
        ["high_churn_score", "contract_month_to_month"],
        [],
        offers=_menu(),
    )
    ids = [m["offer_id"] for m in matches]
    assert "OFF_PREVENT" in ids
    assert "OFF_CONTRACT" in ids
    assert "OFF_UNRELATED" not in ids
    assert matches[0]["match_score"] >= matches[-1]["match_score"]
    # Single best helper still works
    best = match_offer(["high_churn_score"], [], offers=_menu())
    assert best and best["offer_id"] == "OFF_PREVENT"


def test_high_risk_card_has_suggested_offers_list():
    row = {
        "customer_id": "ABCD-1234",
        "monthly_charge": 90.0,
        "contract": "Month-to-month",
        "churn_score": 82,
        "phone_service": "Yes",
        "internet_service": "Yes",
        "online_security": "No",
        "premium_tech_support": "No",
        "high_risk": "Yes",
        "tenure_months": 4,
        "satisfaction_score": 2,
        "unlimited_data": "No",
        "avg_monthly_gb": 50,
    }
    card = build_customer_card(row)
    assert card["high_risk"] is True
    assert card["campaign_eligible"] is True
    assert card["churn_score"] == 82
    assert card["services"]["phone_service"] is True
    assert card["services"]["internet_service"] is True
    assert "UnlimitedData" in card["services"]["missing"]
    assert "OnlineSecurity" in card["services"]["missing"]
    assert any(f["code"] == "high_churn_score" for f in card["risk_factors"])
    assert isinstance(card["suggested_offers"], list)
    assert len(card["suggested_offers"]) >= 2
    assert card["primary_offer_id"] == card["suggested_offers"][0]["offer_id"]
    assert card["suggested_campaign"]
    assert card["suggested_campaign"]["offer_id"] == card["primary_offer_id"]
    # Dominant problems (high score / price / m2m / satisfaction) should beat bare service gaps.
    assert card["primary_offer_id"] in {
        "OFF_PREVENT",
        "OFF_PRICE",
        "OFF_CONTRACT",
        "OFF_SUPPORT",
        "OFF_BUNDLE",
        "OFF_SENIOR",
    }
    assert card["suggested_offers"][0]["confidence_score"] >= card["suggested_offers"][-1]["confidence_score"]
    assert card["suggested_campaign"]["confidence_level"] in {"high", "medium", "low"}
    assert "82/100" in card["suggested_campaign"]["why"]
    assert card["suggested_campaign"]["churn_risk"]["churn_score"] == 82
    assert card["suggested_campaign"]["churn_risk"]["factors"]
    for index, offer in enumerate(card["suggested_offers"], start=1):
        assert offer["rank"] == index
        assert offer["offer_id"]
        assert offer["suggested_resolution"]
        assert offer["suggested_by"] in {"rules", "graph"}
        assert "churn score" in offer["suggested_resolution"].lower() or "Recommend" in offer["suggested_resolution"]


def test_low_risk_card_has_empty_suggested_offers():
    row = {
        "customer_id": "SAFE-9999",
        "monthly_charge": 40.0,
        "contract": "Two year",
        "churn_score": 20,
        "phone_service": "Yes",
        "internet_service": "Yes",
        "online_security": "Yes",
        "premium_tech_support": "Yes",
        "high_risk": "No",
        "tenure_months": 36,
        "satisfaction_score": 5,
        "unlimited_data": "Yes",
        "avg_monthly_gb": 10,
    }
    card = build_customer_card(row)
    assert card["high_risk"] is False
    assert card["suggested_offers"] == []
    assert card["primary_offer_id"] is None


def test_build_suggested_offers_fallback_when_no_tag_match():
    offers = build_suggested_offers(
        high_risk=True,
        risk_factors=[{"code": "totally_unknown_signal", "label": "Unknown"}],
        offers=_menu(),
    )
    assert len(offers) == 1
    assert offers[0]["offer_id"] == "OFF_PREVENT"


def test_problem_signals_outrank_service_gaps():
    """Price/churn problems should beat a generic missing-unlimited upsell."""
    offers = build_suggested_offers(
        high_risk=True,
        risk_factors=[
            {"code": "high_churn_score", "label": "High risk", "weight": 0.76},
            {"code": "price_sensitivity", "label": "Price pressure", "weight": 0.6},
        ],
        services={
            "internet_service": True,
            "unlimited_data": False,
            "avg_monthly_gb": 20,
            "churn_score": 76,
            "satisfaction_score": 2,
            "monthly_charge": 82,
            "missing": ["UnlimitedData"],
            "active": [{"name": "Internet"}],
        },
        offers=_menu()
        + [
            {
                "offer_id": "OFF_UNLIM",
                "name": "Unlimited data upgrade",
                "description": "Unlimited",
                "addresses_patterns": ["unlimited_data", "heavy_usage_no_unlimited", "avg_monthly_gb"],
                "channel": "digital",
                "priority": 1,
            },
            {
                "offer_id": "OFF_PRICE",
                "name": "Price relief plan",
                "description": "Lower cost",
                "addresses_patterns": ["price_sensitivity", "monthly_charge", "low_satisfaction"],
                "channel": "care",
                "priority": 2,
            },
        ],
    )
    assert offers
    assert offers[0]["offer_id"] in {"OFF_PREVENT", "OFF_PRICE"}
    assert offers[0]["offer_id"] != "OFF_UNLIM"
    assert offers[0].get("campaign_type") == "retention"


def test_suggestions_include_confidence_and_rank_best_fit_first():
    offers = build_suggested_offers(
        high_risk=True,
        risk_factors=[
            {"code": "price_sensitivity", "label": "Price pressure", "weight": 0.9},
            {"code": "contract_month_to_month", "label": "Month to month", "weight": 0.2},
        ],
        services={
            "internet_service": True,
            "unlimited_data": False,
            "churn_score": 80,
            "satisfaction_score": 2,
            "monthly_charge": 90,
        },
        offers=_menu()
        + [
            {
                "offer_id": "OFF_PRICE",
                "name": "Price relief plan",
                "description": "Lower cost",
                "addresses_patterns": ["price_sensitivity", "monthly_charge", "low_satisfaction"],
                "channel": "care",
                "priority": 2,
            },
            {
                "offer_id": "OFF_UNLIM",
                "name": "Unlimited data upgrade",
                "description": "Unlimited",
                "addresses_patterns": ["unlimited_data", "heavy_usage_no_unlimited"],
                "channel": "digital",
                "priority": 1,
            },
        ],
        graph_offers=[{
            "offer_id": "OFF_UNRELATED",
            "graph_score": 30.0,
            "reason": "Graph hit for an unrelated offer",
        }],
    )
    assert offers[0]["offer_id"] == "OFF_PRICE"
    assert offers[0]["confidence_level"] == "high"
    assert offers[0]["confidence_score"] >= offers[1]["confidence_score"]
    assert any("strongest risk factor" in reason for reason in offers[0]["confidence_reasons"])
    assert offers[0]["rank"] == 1


def test_same_stored_risk_code_does_not_tie_every_offer():
    """Older suggestions stamped every offer with the customer's first risk code."""
    from app.analysis.customer_campaigns import rank_offers_by_confidence

    ranked = rank_offers_by_confidence(
        [
            {
                "offer_id": offer_id,
                "offer_name": offer_id,
                "matched_patterns": ["high_churn_score"],
                "suggested_by": "graph",
                "match_score": 28,
                "priority": 1,
                "campaign_type": "retention",
            }
            for offer_id in ("OFF_PREVENT", "OFF_BUNDLE", "OFF_DEVICE", "OFF_FIBER")
        ],
        risk_factors=[{"code": "high_churn_score", "label": "High risk", "weight": 0.8}],
        services={
            "churn_score": 80,
            "internet_service": True,
            "satisfaction_score": 4,
            "monthly_charge": 50,
            "contract": "Month-to-month",
        },
    )
    scores = [offer["confidence_score"] for offer in ranked]
    assert ranked[0]["offer_id"] == "OFF_PREVENT"
    assert ranked[-1]["offer_id"] == "OFF_FIBER"
    assert scores[0] > scores[1]
    assert len(set(scores)) >= 3
    assert scores[-1] < 50


def test_graph_offers_boost_matching():
    offers = build_suggested_offers(
        high_risk=True,
        risk_factors=[{"code": "no_tech_support", "label": "No support", "weight": 0.45}],
        services={"internet_service": True, "premium_tech_support": False, "churn_score": 70},
        offers=_menu(),
        graph_offers=[{
            "offer_id": "OFF_SUPPORT",
            "graph_score": 8.0,
            "reason": "Neo4j: missing premium support",
        }],
    )
    assert offers[0]["offer_id"] == "OFF_SUPPORT"
    assert offers[0]["suggested_by"] == "graph"


def test_enrich_profile_keeps_suggested_offers():
    rows = [
        {
            "customer_id": "c1",
            "monthly_charge": 100.0,
            "contract": "Month-to-month",
            "churn_score": 80,
            "phone_service": "Yes",
            "internet_service": "Yes",
            "high_risk": "Yes",
            "tenure_months": 12,
            "satisfaction_score": 2,
        },
        {
            "customer_id": "c2",
            "monthly_charge": 50.0,
            "contract": "Two year",
            "churn_score": 15,
            "phone_service": "Yes",
            "internet_service": "Yes",
            "high_risk": "No",
            "tenure_months": 40,
            "satisfaction_score": 5,
        },
    ]
    profile = enrich_profile_with_customers({}, rows)
    high = next(c for c in profile["customers_detail"] if c["customer_id"] == "c1")
    low = next(c for c in profile["customers_detail"] if c["customer_id"] == "c2")
    assert high["suggested_offers"]
    assert low["suggested_offers"] == []
