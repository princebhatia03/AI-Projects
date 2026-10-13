"""Customer service footprint helpers."""

from app.analysis.customer_services import service_match_needles, services_snapshot, uses_rows_for_graph


def test_services_snapshot_active_and_missing():
    snap = services_snapshot({
        "phone_service": "Yes",
        "internet_service": "Yes",
        "internet_type": "DSL",
        "unlimited_data": "No",
        "online_security": "No",
        "premium_tech_support": "Yes",
        "multiple_lines": "No",
        "contract": "Month-to-month",
        "avg_monthly_gb": 55,
        "churn_score": 88,
        "satisfaction_score": 2,
        "monthly_charge": 95,
    })
    names = {item["name"] for item in snap["active"]}
    assert names == {"Phone", "Internet", "PremiumTechSupport"}
    assert "UnlimitedData" in snap["missing"]
    assert "OnlineSecurity" in snap["missing"]
    assert snap["churn_score"] == 88


def test_service_needles_drive_offer_tags():
    snap = services_snapshot({
        "phone_service": "Yes",
        "internet_service": "No",
        "unlimited_data": "No",
        "online_security": "No",
        "premium_tech_support": "No",
        "multiple_lines": "No",
        "contract": "Month-to-month",
        "churn_score": 70,
        "satisfaction_score": 2,
        "monthly_charge": 40,
    })
    needles = service_match_needles(snap)
    assert "phone_only_no_internet" in needles
    assert "contract_month_to_month" in needles
    assert "high_churn_score" in needles


def test_uses_rows_for_graph():
    snap = services_snapshot({
        "phone_service": "Yes",
        "internet_service": "Yes",
        "internet_type": "Fiber",
        "unlimited_data": "Yes",
        "online_security": "No",
        "premium_tech_support": "No",
        "multiple_lines": "No",
        "avg_monthly_gb": 20,
    })
    rows = uses_rows_for_graph("C1", snap)
    assert {r["service"] for r in rows} == {"Phone", "Internet", "UnlimitedData"}
    internet = next(r for r in rows if r["service"] == "Internet")
    assert internet["detail"] == "Fiber"
