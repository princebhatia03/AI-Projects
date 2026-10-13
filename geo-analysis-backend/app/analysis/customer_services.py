"""Per-customer service footprint used for risk, offers, and Neo4j."""

from __future__ import annotations

from typing import Any


# Canonical service catalog keys (Neo4j :Service.name).
SERVICE_CATALOG = (
    "Phone",
    "MultipleLines",
    "Internet",
    "UnlimitedData",
    "OnlineSecurity",
    "PremiumTechSupport",
)


def _yes(value: Any) -> bool:
    return value == "Yes" or value is True


def services_snapshot(row: dict) -> dict[str, Any]:
    """Compact service inventory + gaps for one customer row."""
    phone = _yes(row.get("phone_service"))
    internet = _yes(row.get("internet_service"))
    multiple = _yes(row.get("multiple_lines"))
    unlimited = _yes(row.get("unlimited_data"))
    security = _yes(row.get("online_security"))
    support = _yes(row.get("premium_tech_support"))
    internet_type = str(row.get("internet_type") or "").strip() or None
    contract = str(row.get("contract") or "").strip() or None
    avg_gb = row.get("avg_monthly_gb")

    active: list[dict[str, Any]] = []
    if phone:
        active.append({"name": "Phone", "detail": None})
    if multiple:
        active.append({"name": "MultipleLines", "detail": None})
    if internet:
        active.append({
            "name": "Internet",
            "detail": internet_type,
            "avg_monthly_gb": avg_gb if isinstance(avg_gb, (int, float)) else None,
        })
    if unlimited:
        active.append({"name": "UnlimitedData", "detail": None})
    if security:
        active.append({"name": "OnlineSecurity", "detail": None})
    if support:
        active.append({"name": "PremiumTechSupport", "detail": None})

    missing: list[str] = []
    if phone and not internet:
        missing.append("Internet")
    if internet and not unlimited:
        missing.append("UnlimitedData")
    if internet and not security:
        missing.append("OnlineSecurity")
    if internet and not support:
        missing.append("PremiumTechSupport")
    if phone and not multiple:
        missing.append("MultipleLines")

    return {
        "active": active,
        "missing": missing,
        "contract": contract,
        "internet_type": internet_type,
        "phone_service": phone,
        "internet_service": internet,
        "multiple_lines": multiple,
        "unlimited_data": unlimited,
        "online_security": security,
        "premium_tech_support": support,
        "avg_monthly_gb": avg_gb if isinstance(avg_gb, (int, float)) else None,
        "monthly_charge": row.get("monthly_charge"),
        "tenure_months": row.get("tenure_months"),
        "churn_score": row.get("churn_score"),
        "satisfaction_score": row.get("satisfaction_score"),
    }


def service_match_needles(services: dict[str, Any] | None) -> list[str]:
    """Extra offer-tag needles derived from the service footprint."""
    if not services:
        return []
    needles: list[str] = []
    if services.get("phone_service") and not services.get("internet_service"):
        needles.append("phone_only_no_internet")
    if services.get("internet_service") and not services.get("unlimited_data"):
        needles.extend(["unlimited_data", "heavy_usage_no_unlimited", "avg_monthly_gb"])
    if services.get("internet_service") and not services.get("online_security"):
        needles.extend(["no_security_addon", "online_security"])
    if services.get("internet_service") and not services.get("premium_tech_support"):
        needles.extend(["no_tech_support", "premium_tech_support"])
    if services.get("dependents"):
        needles.append("dependents")
    contract = str(services.get("contract") or "").lower()
    if "month" in contract:
        needles.extend(["contract_month_to_month", "contract"])
    internet_type = str(services.get("internet_type") or "").lower()
    if internet_type:
        needles.append("internet_type")
        if "dsl" in internet_type or "cable" in internet_type:
            needles.append("fiber")
    gb = services.get("avg_monthly_gb")
    if isinstance(gb, (int, float)) and gb >= 40 and not services.get("unlimited_data"):
        needles.append("heavy_usage_no_unlimited")
    score = services.get("churn_score")
    if isinstance(score, (int, float)) and score >= 65:
        needles.extend(["high_churn_score", "churn_score", "high_risk"])
    sat = services.get("satisfaction_score")
    if isinstance(sat, (int, float)) and sat <= 3:
        needles.append("low_satisfaction")
    monthly = services.get("monthly_charge")
    if isinstance(monthly, (int, float)) and monthly >= 80 and isinstance(sat, (int, float)) and sat <= 3:
        needles.extend(["price_sensitivity", "monthly_charge"])
    return needles


def uses_rows_for_graph(customer_id: str, services: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Rows for (:Customer)-[:USES]->(:Service) MERGE."""
    if not services:
        return []
    rows: list[dict[str, Any]] = []
    for item in services.get("active") or []:
        name = item.get("name")
        if not name:
            continue
        rows.append({
            "customer_id": customer_id,
            "service": name,
            "detail": item.get("detail"),
            "avg_monthly_gb": item.get("avg_monthly_gb"),
        })
    return rows
