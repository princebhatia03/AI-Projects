"""Campaign trigger defaults to customer primary suggested offer."""

from app.pipeline import state as pipeline_state


def test_trigger_uses_customer_primary_offer_when_omitted(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_state, "artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.storage.campaigns_db.insert_campaign",
        lambda record: record,
    )
    monkeypatch.setattr(
        "app.storage.campaigns_db.list_campaigns",
        lambda **kwargs: [],
    )

    with pipeline_state._lock:
        pipeline_state._STATE["profiles"] = [{
            "zip_code": "56080",
            "city": "Koblenz",
            "customers_detail": [{
                "customer_id": "CUST-1",
                "customer_ref": "…ST-1",
                "high_risk": True,
                "campaign_eligible": True,
                "campaign_status": "eligible",
                "clv_eur": 1200.0,
                "primary_offer_id": "OFF_CONTRACT",
                "suggested_offers": [
                    {"offer_id": "OFF_CONTRACT", "rank": 1},
                    {"offer_id": "OFF_PREVENT", "rank": 2},
                ],
            }],
        }]
        pipeline_state._STATE["diagnoses"] = {
            "56080": {"offer_id": "OFF_PREVENT"},
        }
        pipeline_state._STATE["campaigns"] = []

    result = pipeline_state.trigger_campaign_for_zip(
        "56080",
        customer_ids=["CUST-1"],
        all_high_risk=False,
        offer_id=None,
    )
    assert result["ok"] is True
    assert result["campaign"]["offer_id"] == "OFF_CONTRACT"


def test_trigger_honors_explicit_offer_id(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_state, "artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.storage.campaigns_db.insert_campaign",
        lambda record: record,
    )
    monkeypatch.setattr(
        "app.storage.campaigns_db.list_campaigns",
        lambda **kwargs: [],
    )

    with pipeline_state._lock:
        pipeline_state._STATE["profiles"] = [{
            "zip_code": "56080",
            "city": "Koblenz",
            "customers_detail": [{
                "customer_id": "CUST-1",
                "customer_ref": "…ST-1",
                "high_risk": True,
                "campaign_eligible": True,
                "campaign_status": "eligible",
                "clv_eur": 1200.0,
                "primary_offer_id": "OFF_CONTRACT",
                "suggested_offers": [
                    {"offer_id": "OFF_CONTRACT", "rank": 1},
                    {"offer_id": "OFF_PREVENT", "rank": 2},
                ],
            }],
        }]
        pipeline_state._STATE["diagnoses"] = {}
        pipeline_state._STATE["campaigns"] = []

    result = pipeline_state.trigger_campaign_for_zip(
        "56080",
        customer_ids=["CUST-1"],
        all_high_risk=False,
        offer_id="OFF_PREVENT",
    )
    assert result["ok"] is True
    assert result["campaign"]["offer_id"] == "OFF_PREVENT"
    assert result["campaign"]["selection"] == "explicit"
    assert result["campaign"]["assignments"][0]["offer_id"] == "OFF_PREVENT"


def test_trigger_sends_each_high_risk_customer_their_best_offer(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_state, "artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.storage.campaigns_db.insert_campaign",
        lambda record: record,
    )
    monkeypatch.setattr(
        "app.storage.campaigns_db.list_campaigns",
        lambda **kwargs: [],
    )

    with pipeline_state._lock:
        pipeline_state._STATE["profiles"] = [{
            "zip_code": "56080",
            "city": "Koblenz",
            "customers_detail": [
                {
                    "customer_id": "CUST-1",
                    "customer_ref": "…ST-1",
                    "high_risk": True,
                    "campaign_eligible": True,
                    "campaign_status": "eligible",
                    "clv_eur": 1200.0,
                    "primary_offer_id": "OFF_CONTRACT",
                    "suggested_offers": [
                        {
                            "offer_id": "OFF_CONTRACT",
                            "offer_name": "Annual contract perk",
                            "rank": 1,
                            "confidence_score": 91,
                            "confidence_level": "high",
                        },
                        {
                            "offer_id": "OFF_PREVENT",
                            "offer_name": "Preventive loyalty credit",
                            "rank": 2,
                            "confidence_score": 40,
                            "confidence_level": "low",
                        },
                    ],
                },
                {
                    "customer_id": "CUST-2",
                    "customer_ref": "…ST-2",
                    "high_risk": True,
                    "campaign_eligible": True,
                    "campaign_status": "eligible",
                    "clv_eur": 800.0,
                    "primary_offer_id": "OFF_PREVENT",
                    "suggested_offers": [
                        {
                            "offer_id": "OFF_PRICE",
                            "offer_name": "Price relief plan",
                            "rank": 2,
                            "confidence_score": 88,
                            "confidence_level": "high",
                        },
                        {
                            "offer_id": "OFF_PREVENT",
                            "offer_name": "Preventive loyalty credit",
                            "rank": 1,
                            "confidence_score": 55,
                            "confidence_level": "medium",
                        },
                    ],
                },
                {
                    "customer_id": "CUST-SAFE",
                    "customer_ref": "…SAFE",
                    "high_risk": False,
                    "campaign_eligible": False,
                    "campaign_status": "not_eligible",
                    "clv_eur": 400.0,
                },
            ],
        }]
        pipeline_state._STATE["diagnoses"] = {
            "56080": {"offer_id": "OFF_PREVENT"},
        }
        pipeline_state._STATE["campaigns"] = []

    result = pipeline_state.trigger_campaign_for_zip(
        "56080",
        customer_ids=None,
        all_high_risk=True,
        offer_id=None,
    )
    assert result["ok"] is True
    assert result["campaign"]["selection"] == "highest_confidence"
    assert result["campaign"]["customer_count"] == 2
    assert result["campaign"]["offer_id"] is None
    sent = {
        item["customer_id"]: item["offer_id"]
        for item in result["campaign"]["assignments"]
    }
    assert sent == {"CUST-1": "OFF_CONTRACT", "CUST-2": "OFF_PRICE"}


def test_trigger_by_risk_levels_targets_medium_and_skips_triggered(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_state, "artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr("app.storage.campaigns_db.insert_campaign", lambda record: record)
    monkeypatch.setattr("app.storage.campaigns_db.list_campaigns", lambda **kwargs: [])

    with pipeline_state._lock:
        pipeline_state._STATE["profiles"] = [{
            "zip_code": "56080",
            "city": "Koblenz",
            "customers_detail": [
                {
                    "customer_id": "HIGH-DONE",
                    "customer_ref": "…DONE",
                    "churn_prediction": "High",
                    "high_risk": True,
                    "campaign_eligible": True,
                    "campaign_status": "triggered",
                    "clv_eur": 900.0,
                },
                {
                    "customer_id": "MED-1",
                    "customer_ref": "…ED-1",
                    "churn_prediction": "Medium",
                    "high_risk": False,
                    "campaign_eligible": False,
                    "campaign_status": "not_eligible",
                    "clv_eur": 700.0,
                    "risk_factors": [
                        {"code": "contract_month_to_month", "label": "Month-to-month contract", "weight": 0.7},
                    ],
                    "services": {"churn_score": 55, "contract": "Month-to-month"},
                },
                {
                    "customer_id": "LOW-1",
                    "customer_ref": "…OW-1",
                    "churn_prediction": "Low",
                    "high_risk": False,
                    "campaign_eligible": False,
                    "campaign_status": "not_eligible",
                    "clv_eur": 300.0,
                },
            ],
        }]
        pipeline_state._STATE["diagnoses"] = {}
        pipeline_state._STATE["campaigns"] = []

    result = pipeline_state.trigger_campaign_for_zip(
        "56080",
        customer_ids=None,
        all_high_risk=False,
        offer_id=None,
        risk_levels=["High", "Medium"],
    )
    assert result["ok"] is True
    assert result["campaign"]["customer_count"] == 1
    assert result["campaign"]["risk_levels"] == ["High", "Medium"]
    assignment = result["campaign"]["assignments"][0]
    assert assignment["customer_id"] == "MED-1"
    assert assignment["offer_id"]
    assert assignment["confidence_score"] is not None
