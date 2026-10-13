"""Euro business impact, contract-line churn, and per-customer CLV cards."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app import config

CONTRACT_TYPES = ("Fixed", "Mobile", "Bundle")


def contract_type(row: dict) -> str:
    """Map phone/internet flags to Fixed / Mobile / Bundle lines."""
    phone = row.get("phone_service") == "Yes"
    internet = row.get("internet_service") == "Yes"
    if phone and internet:
        return "Bundle"
    if internet:
        return "Fixed"
    if phone:
        return "Mobile"
    return "Fixed"


def mask_customer_id(customer_id: str | None) -> str:
    text = str(customer_id or "").strip()
    if not text:
        return "unknown"
    if len(text) <= 4:
        return f"****{text}"
    return f"…{text[-4:]}"


def _monthly_discount_rate() -> float:
    """Convert annual WACC-style discount to a monthly rate."""
    annual = max(0.0, float(config.CLV_ANNUAL_DISCOUNT_RATE))
    return (1.0 + annual) ** (1.0 / 12.0) - 1.0


def _contract_monthly_churn(contract: str | None) -> float:
    """Baseline monthly churn by commitment type (telecom retention curves)."""
    text = str(contract or "").strip().lower().replace("_", " ").replace("-", " ")
    text = " ".join(text.split())
    if "month" in text:
        return max(1e-4, float(config.CLV_MONTHLY_CHURN_MONTH_TO_MONTH))
    if text.startswith("one") or text == "1 year" or "1 yr" in text:
        return max(1e-4, float(config.CLV_MONTHLY_CHURN_ONE_YEAR))
    if text.startswith("two") or text == "2 year" or "2 yr" in text:
        return max(1e-4, float(config.CLV_MONTHLY_CHURN_TWO_YEAR))
    return max(1e-4, float(config.CLV_MONTHLY_CHURN_DEFAULT))


def customer_clv_eur(row: dict) -> float:
    """Telecom discounted CLV in EUR.

    Standard operator formula (monthly units):

        CLV = (ARPU × Gross Margin) / (Monthly Churn + Monthly Discount)

    Equivalent to contribution margin × expected lifetime with time value of
    money. Contract-type baseline churn is used here; individual churn risk is
    applied separately via ``expected_loss = CLV × churn_probability``.
    """
    arpu = float(row.get("monthly_charge") or 0.0)
    if arpu <= 0:
        return 0.0
    margin = max(0.0, min(1.0, float(config.CLV_GROSS_MARGIN)))
    contribution = arpu * margin
    churn = _contract_monthly_churn(row.get("contract"))
    discount = _monthly_discount_rate()
    return round(contribution / (churn + discount), 2)


def churn_probability(row: dict) -> float:
    score = row.get("churn_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return max(0.0, min(1.0, float(score) / 100.0))
    return 1.0 if row.get("high_risk") == "Yes" else 0.2


def churn_prediction_label(probability: float, high_risk: bool) -> str:
    if high_risk or probability >= 0.65:
        return "High"
    if probability >= 0.40:
        return "Medium"
    return "Low"


def build_customer_card(
    row: dict,
    *,
    graph_offers: list[dict] | None = None,
) -> dict[str, Any]:
    from app.analysis.customer_campaigns import (
        build_suggested_campaign,
        build_suggested_offers,
    )
    from app.analysis.customer_risk import explain_customer_risk
    from app.analysis.customer_services import services_snapshot

    probability = churn_probability(row)
    high_risk = row.get("high_risk") == "Yes" or probability >= 0.65
    clv = customer_clv_eur(row)
    explanation = explain_customer_risk(row)
    risk_factors = explanation.get("risk_factors") or []
    services = services_snapshot(row)
    suggested_offers = build_suggested_offers(
        high_risk=high_risk,
        risk_factors=risk_factors,
        services=services,
        graph_offers=graph_offers,
    )
    primary = suggested_offers[0]["offer_id"] if suggested_offers else None
    suggested_campaign = build_suggested_campaign(suggested_offers)
    churn_score = row.get("churn_score")
    return {
        "customer_id": str(row.get("customer_id") or ""),
        "customer_ref": mask_customer_id(row.get("customer_id")),
        "contract_type": contract_type(row),
        "churn_prediction": churn_prediction_label(probability, high_risk),
        "churn_probability": round(probability, 3),
        "churn_score": int(churn_score) if isinstance(churn_score, (int, float)) and not isinstance(churn_score, bool) else None,
        "clv_eur": clv,
        "monthly_charge_eur": round(float(row.get("monthly_charge") or 0.0), 2),
        "tenure_months": row.get("tenure_months"),
        "satisfaction_score": row.get("satisfaction_score"),
        "high_risk": high_risk,
        "campaign_eligible": high_risk,
        "campaign_status": "eligible" if high_risk else "not_eligible",
        # Narrative is agent-only; factors stay for the explain dialog agent input.
        "risk_why": None,
        "risk_factors": risk_factors,
        "risk_why_source": None,
        "services": services,
        "suggested_offers": suggested_offers,
        "suggested_campaign": suggested_campaign,
        "primary_offer_id": primary,
    }


def churn_by_contract(cards: list[dict]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict]] = {name: [] for name in CONTRACT_TYPES}
    for card in cards:
        name = card.get("contract_type") or "Fixed"
        if name not in buckets:
            buckets[name] = []
        buckets[name].append(card)

    out: list[dict[str, Any]] = []
    for name in CONTRACT_TYPES:
        group = buckets.get(name) or []
        if not group:
            out.append({
                "contract_type": name,
                "customers": 0,
                "high_risk_customers": 0,
                "churn_rate": None,
                "at_risk_clv_eur": 0.0,
                "total_clv_eur": 0.0,
            })
            continue
        high = [c for c in group if c.get("high_risk")]
        out.append({
            "contract_type": name,
            "customers": len(group),
            "high_risk_customers": len(high),
            "churn_rate": round(len(high) / len(group), 4),
            "at_risk_clv_eur": round(sum(float(c.get("clv_eur") or 0) for c in high), 2),
            "total_clv_eur": round(sum(float(c.get("clv_eur") or 0) for c in group), 2),
        })
    return out


def enrich_profile_with_customers(profile: dict, zip_rows: list[dict]) -> dict:
    """Attach customer cards + euro impact summaries onto a pincode profile."""
    cards = [build_customer_card(row) for row in zip_rows]
    cards.sort(
        key=lambda item: (
            0 if item.get("high_risk") else 1,
            -(item.get("clv_eur") or 0),
            item.get("customer_ref") or "",
        ),
    )
    high_risk = [c for c in cards if c.get("high_risk")]
    total_clv = round(sum(float(c.get("clv_eur") or 0) for c in cards), 2)
    at_risk_clv = round(sum(float(c.get("clv_eur") or 0) for c in high_risk), 2)
    expected_loss = round(
        sum(float(c.get("clv_eur") or 0) * float(c.get("churn_probability") or 0) for c in cards),
        2,
    )
    by_contract = churn_by_contract(cards)

    profile["customers_detail"] = cards
    profile["high_risk_customers"] = len(high_risk)
    profile["total_clv_eur"] = total_clv
    profile["at_risk_clv_eur"] = at_risk_clv
    profile["business_impact_eur"] = at_risk_clv
    profile["expected_loss_eur"] = expected_loss
    profile["churn_by_contract"] = by_contract
    profile["currency"] = "EUR"
    return profile


def apply_campaign_status(
    cards: list[dict],
    *,
    customer_ids: list[str] | None = None,
    all_high_risk: bool = False,
    campaign_id: str,
) -> list[dict]:
    """Mark matching customers as campaign-triggered; returns updated cards."""
    selected = set(customer_ids or [])
    updated: list[dict] = []
    for card in cards:
        next_card = dict(card)
        match = next_card.get("customer_id") in selected or next_card.get("customer_ref") in selected
        if all_high_risk and next_card.get("high_risk"):
            match = True
        if match and next_card.get("campaign_eligible"):
            next_card["campaign_status"] = "triggered"
            next_card["campaign_id"] = campaign_id
        updated.append(next_card)
    return updated


def summarize_campaigns(campaigns: list[dict]) -> dict[str, Any]:
    by_zip: dict[str, int] = defaultdict(int)
    for item in campaigns:
        by_zip[str(item.get("zip_code"))] += int(item.get("customer_count") or 0)
    return {"campaign_count": len(campaigns), "customers_by_zip": dict(by_zip)}
