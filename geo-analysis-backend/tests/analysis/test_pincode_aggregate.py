from app.analysis.loader import as_active_customer
from app.analysis.pattern_catalog import default_catalog, validate_catalog
from app.analysis.pincode_aggregate import aggregate_by_pincode
from app.analysis.offers import match_offer, load_offers
from app.analysis.diagnosis import diagnose_pincode


def _rows():
    base = {
        "state": "CA",
        "population": 1000,
        "age": 40,
        "phone_service": "Yes",
        "internet_service": "Yes",
        "internet_type": "Fiber Optic",
        "avg_monthly_gb": 50.0,
        "online_security": "No",
        "premium_tech_support": "No",
        "contract": "Month-to-Month",
        "monthly_charge": 70.0,
        "total_extra_data_charges": 10.0,
        "tenure_months": 12,
        "offer": "None",
        "satisfaction_score": 3,
        "churn_score": 70,
        "churn_category": "Competitor",
        "churn_reason": "Competitor offered more data",
        "cltv": 2000,
        "under_30": "No",
        "senior_citizen": "No",
        "married": "Yes",
        "dependents": "No",
        "number_of_dependents": 0,
        "multiple_lines": "No",
    }
    rows = []
    for i in range(40):
        rows.append(as_active_customer({
            **base,
            "customer_id": f"a{i}",
            "zip_code": "90001",
            "city": "Los Angeles",
            "unlimited_data": "No",
            "customer_status": "Churned",
            "avg_monthly_gb": 80.0,
            "total_extra_data_charges": 25.0,
            "churn_score": 80,
            "satisfaction_score": 2,
        }))
    for i in range(40):
        rows.append(as_active_customer({
            **base,
            "customer_id": f"b{i}",
            "zip_code": "94107",
            "city": "San Francisco",
            "unlimited_data": "Yes",
            "customer_status": "Churned",
            "avg_monthly_gb": 20.0,
            "total_extra_data_charges": 0.0,
            "contract": "Two Year",
            "churn_score": 30,
            "satisfaction_score": 4,
        }))
    return rows


def test_active_framing_clears_past_churn():
    row = as_active_customer({
        "customer_status": "Churned",
        "churn_category": "Price",
        "churn_reason": "Too expensive",
        "churn_score": 80,
        "satisfaction_score": 1,
    })
    assert row["customer_status"] == "Active"
    assert row["churn_category"] is None
    assert row["churn_reason"] is None
    assert row["high_risk"] == "Yes"
    assert row["low_satisfaction"] == "Yes"


def test_aggregate_risk_rates():
    catalog = validate_catalog(default_catalog(), columns=list(_rows()[0].keys()))
    profiles = aggregate_by_pincode(_rows(), catalog)
    by_zip = {p["zip_code"]: p for p in profiles}
    assert by_zip["90001"]["risk_rate"] == 1.0
    assert by_zip["94107"]["risk_rate"] == 0.0
    assert by_zip["90001"]["gap_score"] >= by_zip["94107"]["gap_score"]
    assert all(r["customer_status"] == "Active" for r in _rows())


def test_heavy_usage_pattern_present():
    catalog = validate_catalog(default_catalog(), columns=list(_rows()[0].keys()))
    profiles = aggregate_by_pincode(_rows(), catalog)
    la = next(p for p in profiles if p["zip_code"] == "90001")
    ids = {p["pattern_id"] for p in la["patterns"]}
    assert "heavy_usage_no_unlimited" in ids


def test_diagnose_assigns_menu_offer():
    from app.analysis.diagnosis import diagnose_many

    catalog = validate_catalog(default_catalog(), columns=list(_rows()[0].keys()))
    profiles = aggregate_by_pincode(_rows(), catalog)
    la = next(p for p in profiles if p["zip_code"] == "90001")
    diagnosis = diagnose_pincode(la, catalog=catalog, offers=load_offers(), polish=False)
    assert diagnosis["offer_id"] in {o["offer_id"] for o in load_offers()}
    assert diagnosis["evidence"]
    assert "90001" in diagnosis["problem"]
    assert "predicted" in diagnosis["problem"].lower() or "risk" in diagnosis["problem"].lower() or "gap" in diagnosis["problem"].lower()

    all_dx = diagnose_many(profiles, top_n=0, offers=load_offers())
    assert set(all_dx) == {p["zip_code"] for p in profiles}
    assert all(item["offer_id"] for item in all_dx.values())
    assert all(item["evidence"] for item in all_dx.values())


def test_match_offer_tags():
    offer = match_offer(["heavy_usage_no_unlimited"], ["unlimited_data"], load_offers())
    assert offer is not None
    assert offer["offer_id"] == "OFF_UNLIM"


def test_offers_menu_expanded():
    from app.analysis.offers import fallback_offer

    offers = load_offers()
    assert len(offers) >= 12
    ids = {o["offer_id"] for o in offers}
    assert "OFF_PREVENT" in ids
    assert "OFF_PRICE" in ids
    assert fallback_offer({"risk_rate": 0.5}, offers)["offer_id"] == "OFF_PREVENT"
