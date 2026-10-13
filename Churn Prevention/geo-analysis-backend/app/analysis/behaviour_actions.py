"""Behaviour-based upsell opportunities and AI campaign suggestions per pincode."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from app import config
from app.analysis.business_impact import customer_clv_eur
from app.analysis.offers import load_offers, match_offer


def _behaviour_signals(row: dict) -> list[str]:
    signals: list[str] = []
    if row.get("phone_service") == "Yes" and row.get("internet_service") == "No":
        signals.append("phone_only_no_internet")
    if (
        row.get("internet_service") == "Yes"
        and row.get("unlimited_data") == "No"
        and isinstance(row.get("avg_monthly_gb"), (int, float))
        and float(row["avg_monthly_gb"]) >= 40
    ):
        signals.append("heavy_usage_no_unlimited")
    if row.get("internet_service") == "Yes" and row.get("online_security") == "No":
        signals.append("no_security_addon")
    if row.get("internet_service") == "Yes" and row.get("premium_tech_support") == "No":
        signals.append("no_tech_support")
    if row.get("dependents") == "Yes" and row.get("multiple_lines") == "No":
        signals.append("dependents")
    contract = str(row.get("contract") or "").lower()
    if "month" in contract:
        signals.append("contract_month_to_month")
    if row.get("high_risk") == "Yes" or (
        isinstance(row.get("churn_score"), (int, float)) and row["churn_score"] >= config.HIGH_RISK_SCORE
    ):
        signals.append("high_churn_score")
    if row.get("low_satisfaction") == "Yes" or (
        isinstance(row.get("satisfaction_score"), (int, float))
        and row["satisfaction_score"] <= config.LOW_SATISFACTION
    ):
        signals.append("low_satisfaction")
    monthly = row.get("monthly_charge")
    sat = row.get("satisfaction_score")
    if (
        isinstance(monthly, (int, float))
        and monthly >= 80
        and isinstance(sat, (int, float))
        and sat <= 3
    ):
        signals.append("price_sensitivity")
    return signals


# Yearly ARPU uplifts (€/year) calibrated to DE retail attach deltas (2025):
# - Home broadband: entry DSL/fiber ~€29.95–39.95/mo (1&1 / cable promos)
# - Unlimited step-up: ~€5–8/mo over metered (O2 data options; << Telekom L→XL €25)
# - Security: Telekom Sicherheitspaket M ~€3.95/mo
# - Care/support: Digital Schutzpaket support share ~€6/mo (pack €9.95)
# - Extra line: Telekom PlusCard Kids / entry family ~€9.95–10/mo
UPSELL_RULES: list[dict[str, Any]] = [
    {
        "signal": "phone_only_no_internet",
        "action": "upsell",
        "title": "Home internet",
        "product": "Fixed broadband / fiber",
        "reason": "Phone-only customers with no home internet — clear cross-sell.",
        "offer_hint": "OFF_HOME",
        "monthly_uplift_eur": 30.0,
        "yearly_uplift_eur": 360.0,
    },
    {
        "signal": "heavy_usage_no_unlimited",
        "action": "upsell",
        "title": "Unlimited data",
        "product": "Unlimited mobile / data plan",
        "reason": "Heavy GB use on metered plans — upgrade before overage friction.",
        "offer_hint": "OFF_UNLIM",
        # ~€6/mo incremental (not full unlimited plan price).
        "monthly_uplift_eur": 6.0,
        "yearly_uplift_eur": 72.0,
    },
    {
        "signal": "no_security_addon",
        "action": "upsell",
        "title": "Online security",
        "product": "Security add-on",
        "reason": "Internet without protection — attach security pack.",
        "offer_hint": "OFF_PROTECT",
        "monthly_uplift_eur": 4.0,
        "yearly_uplift_eur": 48.0,
    },
    {
        "signal": "no_tech_support",
        "action": "upsell",
        "title": "Premium support",
        "product": "Premium tech support",
        "reason": "No support cover — upsell care bundle to lift satisfaction.",
        "offer_hint": "OFF_SUPPORT",
        "monthly_uplift_eur": 6.0,
        "yearly_uplift_eur": 72.0,
    },
    {
        "signal": "dependents",
        "action": "upsell",
        "title": "Family lines",
        "product": "Extra line / family plan",
        "reason": "Households with dependents but no multi-line — family plan fit.",
        "offer_hint": "OFF_FAMILY",
        "monthly_uplift_eur": 10.0,
        "yearly_uplift_eur": 120.0,
    },
]

# Campaign take-rate: not every eligible customer buys the attach.
UPSELL_CONVERSION_RATE = 0.20
# Never claim more than this share of matched customers' existing CLV.
UPSELL_GAIN_CAP_OF_CLV = 0.15


def potential_upsell_gain_eur(
    *,
    customers: int,
    yearly_uplift_eur: float,
    addressable_clv_eur: float,
) -> float:
    """Expected first-year incremental contribution (€/year) after take-rate.

    ``customers × yearly_ARPU_uplift × gross_margin × conversion``, capped vs
    addressable CLV so the headline stays conservative.
    """
    if customers <= 0 or yearly_uplift_eur <= 0:
        return 0.0
    margin = max(0.0, min(1.0, float(config.CLV_GROSS_MARGIN)))
    raw = customers * yearly_uplift_eur * margin * UPSELL_CONVERSION_RATE
    cap = max(0.0, addressable_clv_eur) * UPSELL_GAIN_CAP_OF_CLV
    capped = min(raw, cap) if cap > 0 else raw
    return round(capped, 2)


def upsell_addressable_clv_eur(zip_rows: list[dict]) -> float:
    """Unique CLV of customers matching any upsell behaviour rule (no double-count)."""
    upsell_signals = {rule["signal"] for rule in UPSELL_RULES}
    total = 0.0
    for row in zip_rows:
        if set(_behaviour_signals(row)) & upsell_signals:
            total += customer_clv_eur(row)
    return round(total, 2)


def _customer_word(count: int) -> str:
    return "1 customer" if count == 1 else f"{count} customers"


def _numeric_values(rows: list[dict], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return values


def signal_facts(zip_rows: list[dict]) -> dict[str, dict[str, Any]]:
    """Measured evidence behind each behaviour signal in a pincode."""
    grouped: dict[str, list[dict]] = {}
    for row in zip_rows:
        for signal in set(_behaviour_signals(row)):
            grouped.setdefault(signal, []).append(row)

    facts: dict[str, dict[str, Any]] = {}
    for signal, rows in grouped.items():
        count = len(rows)
        detail: dict[str, Any] = {"customers": count}
        if signal == "heavy_usage_no_unlimited":
            usage = _numeric_values(rows, "avg_monthly_gb")
            if usage:
                average = round(sum(usage) / len(usage), 1)
                highest = round(max(usage), 1)
                detail["avg_monthly_gb"] = average
                detail["max_monthly_gb"] = highest
                evidence = [
                    f"{_customer_word(count)} on a metered plan, averaging {average:.0f} GB/month "
                    f"(highest {highest:.0f} GB), with no unlimited data"
                ]
            else:
                evidence = [f"{_customer_word(count)} use a metered plan with no unlimited data"]
        elif signal == "phone_only_no_internet":
            evidence = [f"{_customer_word(count)} have phone service and no home internet"]
        elif signal == "no_security_addon":
            evidence = [f"{_customer_word(count)} have internet and no online security add-on"]
        elif signal == "no_tech_support":
            evidence = [f"{_customer_word(count)} have internet and no premium tech support"]
        elif signal == "dependents":
            evidence = [f"{_customer_word(count)} have dependents and no extra line"]
        elif signal == "high_churn_score":
            scores = _numeric_values(rows, "churn_score")
            if scores:
                average = round(sum(scores) / len(scores))
                detail["avg_churn_score"] = average
                evidence = [
                    f"{_customer_word(count)} predicted to churn, average risk score {average}/100"
                ]
            else:
                evidence = [f"{_customer_word(count)} flagged as high churn risk"]
        elif signal == "low_satisfaction":
            scores = _numeric_values(rows, "satisfaction_score")
            if scores:
                average = round(sum(scores) / len(scores), 1)
                detail["avg_satisfaction"] = average
                evidence = [f"{_customer_word(count)} have low satisfaction, average {average}/5"]
            else:
                evidence = [f"{_customer_word(count)} have low satisfaction"]
        elif signal == "contract_month_to_month":
            evidence = [f"{_customer_word(count)} are on month-to-month contracts"]
        elif signal == "price_sensitivity":
            charges = _numeric_values(rows, "monthly_charge")
            if charges:
                average = round(sum(charges) / len(charges))
                detail["avg_monthly_charge_eur"] = average
                evidence = [
                    f"{_customer_word(count)} pay about €{average}/month with satisfaction at or below 3"
                ]
            else:
                evidence = [f"{_customer_word(count)} show price pressure with weak satisfaction"]
        else:
            evidence = [f"{_customer_word(count)} match {signal.replace('_', ' ')}"]
        facts[signal] = {"customers": count, "evidence": evidence, "detail": detail}
    return facts


def _upsell_why(rule: dict, fact: dict) -> str:
    found = (fact.get("evidence") or ["Matching customers were found in this pincode"])[0]
    reason = str(rule.get("reason") or "").rstrip(".")
    return f"{found}. {reason}."


def explain_campaign(campaign: dict, facts: dict[str, dict], upsells: list[dict]) -> dict[str, Any]:
    """Attach why / churn risk or the upsell evidence the UI should show."""
    item = dict(campaign)
    if item.get("campaign_type") == "upsell":
        upsell = next(
            (entry for entry in upsells if entry.get("offer_id") == item.get("offer_id")),
            None,
        )
        if upsell and upsell.get("why"):
            item["why"] = upsell["why"]
            item["evidence"] = list(upsell.get("evidence") or [])
            return item
        evidence: list[str] = []
        for signal in item.get("behaviour_basis") or []:
            evidence.extend((facts.get(str(signal)) or {}).get("evidence") or [])
        item["evidence"] = evidence
        item["why"] = (
            "Upsell because we found: " + "; ".join(evidence) + "."
            if evidence
            else item.get("objective") or "Upsell based on observed service gaps."
        )
        return item

    evidence = []
    high = facts.get("high_churn_score") or {}
    evidence.extend(high.get("evidence") or [])
    for signal in item.get("behaviour_basis") or []:
        if str(signal) == "high_churn_score":
            continue
        evidence.extend((facts.get(str(signal)) or {}).get("evidence") or [])
    detail = high.get("detail") or {}
    item["evidence"] = evidence
    item["churn_risk"] = {
        "customers": high.get("customers") or 0,
        "avg_churn_score": detail.get("avg_churn_score"),
        "evidence": list(high.get("evidence") or []),
    }
    if evidence:
        item["why"] = "Shown because " + "; ".join(evidence) + "."
    else:
        item["why"] = item.get("objective") or "Shown because these customers are predicted to churn."
    return item


def annotate_campaign_explanations(
    campaigns: list[dict],
    zip_rows: list[dict],
    upsells: list[dict],
) -> list[dict]:
    facts = signal_facts(zip_rows)
    return [explain_campaign(campaign, facts, upsells) for campaign in campaigns]


def build_upsell_opportunities(zip_rows: list[dict], offers: list[dict] | None = None) -> list[dict]:
    """Aggregate behaviour-based upsell opportunities for a pincode."""
    menu = offers or load_offers()
    by_id = {o["offer_id"]: o for o in menu}
    counts: Counter[str] = Counter()
    clv_by_signal: dict[str, float] = {}
    facts = signal_facts(zip_rows)
    for row in zip_rows:
        signals = set(_behaviour_signals(row))
        clv = customer_clv_eur(row)
        for signal in signals:
            counts[signal] += 1
            clv_by_signal[signal] = clv_by_signal.get(signal, 0.0) + clv

    opportunities: list[dict] = []
    for rule in UPSELL_RULES:
        signal = rule["signal"]
        n = counts.get(signal, 0)
        if n <= 0:
            continue
        offer = by_id.get(rule["offer_hint"]) or match_offer([signal], [], menu)
        addressable = round(clv_by_signal.get(signal, 0.0), 2)
        fact = facts.get(signal) or {
            "customers": n,
            "evidence": [f"{_customer_word(n)} match {signal.replace('_', ' ')}"],
            "detail": {"customers": n},
        }
        # Prefer yearly; accept legacy monthly_uplift_eur (×12) if present.
        if rule.get("yearly_uplift_eur") is not None:
            yearly_uplift = float(rule["yearly_uplift_eur"])
        else:
            yearly_uplift = float(rule.get("monthly_uplift_eur") or 8.0) * 12.0
        yearly_upsell = round(n * yearly_uplift, 2)
        opportunities.append({
            "signal": signal,
            "title": rule["title"],
            "product": rule["product"],
            "reason": rule["reason"],
            "customers": n,
            "addressable_clv_eur": addressable,
            "yearly_uplift_eur": yearly_uplift,
            "yearly_upsell_eur": yearly_upsell,
            "potential_gain_eur": potential_upsell_gain_eur(
                customers=n,
                yearly_uplift_eur=yearly_uplift,
                addressable_clv_eur=addressable,
            ),
            "potential_gain_period": "year",
            "offer_id": offer["offer_id"] if offer else rule["offer_hint"],
            "offer_name": offer["name"] if offer else rule["title"],
            "why": _upsell_why(rule, fact),
            "evidence": list(fact.get("evidence") or []),
            "evidence_detail": fact.get("detail") or {"customers": n},
        })
    opportunities.sort(
        key=lambda item: (
            -float(item.get("yearly_upsell_eur") or 0.0),
            -item["potential_gain_eur"],
            -item["customers"],
            -item["addressable_clv_eur"],
        )
    )
    return opportunities[:5]


def build_campaign_drafts(
    zip_rows: list[dict],
    *,
    zip_code: str,
    city: str | None,
    upsells: list[dict] | None = None,
    offers: list[dict] | None = None,
) -> list[dict]:
    """Deterministic campaign drafts from behaviour (used when AI is unavailable)."""
    menu = offers or load_offers()
    by_id = {o["offer_id"]: o for o in menu}
    signal_counts: Counter[str] = Counter()
    high_risk = 0
    for row in zip_rows:
        if row.get("high_risk") == "Yes":
            high_risk += 1
        for signal in _behaviour_signals(row):
            signal_counts[signal] += 1

    drafts: list[dict] = []
    # Retention campaign for high-risk behaviour
    if high_risk > 0:
        offer = by_id.get("OFF_PREVENT") or match_offer(["high_churn_score", "low_satisfaction"], [], menu)
        drafts.append({
            "campaign_type": "retention",
            "name": f"Save at-risk in {city or zip_code}",
            "objective": "Reduce predicted churn among high-risk customers",
            "audience": f"{high_risk} high-risk customers in {zip_code}",
            "behaviour_basis": ["high_churn_score", "low_satisfaction", "contract_month_to_month"],
            "offer_id": offer["offer_id"] if offer else "OFF_PREVENT",
            "offer_name": offer["name"] if offer else "Preventive loyalty credit",
            "channel": offer.get("channel") if offer else "care",
            "priority": 1,
            "suggested_by": "rules",
        })

    for upsell in (upsells or [])[:3]:
        offer = by_id.get(upsell.get("offer_id") or "") or match_offer([upsell["signal"]], [], menu)
        drafts.append({
            "campaign_type": "upsell",
            "name": f"{upsell['title']} push — {city or zip_code}",
            "objective": f"Upsell {upsell['product']} from observed behaviour",
            "audience": f"{upsell['customers']} customers with {upsell['signal'].replace('_', ' ')}",
            "behaviour_basis": [upsell["signal"]],
            "offer_id": offer["offer_id"] if offer else upsell.get("offer_id"),
            "offer_name": offer["name"] if offer else upsell.get("offer_name"),
            "channel": offer.get("channel") if offer else "digital",
            "priority": 2 + len(drafts),
            "suggested_by": "rules",
        })

    # Contract stickiness when month-to-month dominates high risk
    m2m = signal_counts.get("contract_month_to_month", 0)
    if m2m >= max(3, high_risk // 2) and high_risk > 0:
        offer = by_id.get("OFF_CONTRACT")
        if offer:
            drafts.append({
                "campaign_type": "retention",
                "name": f"Lock-in perk — {city or zip_code}",
                "objective": "Move flexible contracts to annual where leave risk is high",
                "audience": f"{m2m} month-to-month customers",
                "behaviour_basis": ["contract_month_to_month", "high_churn_score"],
                "offer_id": offer["offer_id"],
                "offer_name": offer["name"],
                "channel": offer.get("channel") or "retail",
                "priority": 2,
                "suggested_by": "rules",
            })

    drafts.sort(key=lambda item: item.get("priority") or 99)
    return drafts[:4]


def suggest_campaigns_with_ai(
    zip_rows: list[dict],
    *,
    zip_code: str,
    city: str | None,
    upsells: list[dict],
    risk_rate: float | None,
    business_impact_eur: float | None,
    offers: list[dict] | None = None,
) -> list[dict]:
    """Ask LiteLLM to suggest campaigns from behaviour summaries + offer menu."""
    drafts = build_campaign_drafts(
        zip_rows,
        zip_code=zip_code,
        city=city,
        upsells=upsells,
        offers=offers,
    )
    if not config.llm_ready():
        return drafts

    menu = offers or load_offers()
    signal_counts: Counter[str] = Counter()
    for row in zip_rows:
        for signal in _behaviour_signals(row):
            signal_counts[signal] += 1

    facts = {
        "zip_code": zip_code,
        "city": city,
        "customers": len(zip_rows),
        "high_risk_customers": sum(1 for row in zip_rows if row.get("high_risk") == "Yes"),
        "risk_rate": risk_rate,
        "business_impact_eur": business_impact_eur,
        "behaviour_counts": dict(signal_counts.most_common(12)),
        "upsell_opportunities": upsells[:5],
        "offer_menu": [
            {
                "offer_id": o["offer_id"],
                "name": o["name"],
                "description": o.get("description"),
                "addresses_patterns": o.get("addresses_patterns"),
                "channel": o.get("channel"),
            }
            for o in menu
        ],
    }
    prompt = (
        "You are a telco growth & retention planner. "
        "Using ONLY the JSON facts, suggest 2-4 campaigns for this pincode. "
        "Each campaign must map to an offer_id from offer_menu. "
        "Ground every suggestion in behaviour_counts / upsell_opportunities. "
        "Return STRICT JSON array only, no markdown, with objects: "
        "campaign_type (retention|upsell), name, objective, audience, "
        "behaviour_basis (string array), offer_id, channel, priority (1=highest).\n\n"
        f"FACTS:\n{json.dumps(facts)}"
    )
    try:
        import litellm
        from litellm import completion

        config.apply_litellm_env()
        litellm.drop_params = True
        response = completion(
            model=config.litellm_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=1,
            max_completion_tokens=700,
            **config.litellm_call_kwargs(),
        )
        text = (response.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            return drafts
        by_id = {o["offer_id"]: o for o in menu}
        out: list[dict] = []
        for index, item in enumerate(parsed[:4]):
            if not isinstance(item, dict):
                continue
            offer_id = item.get("offer_id")
            offer = by_id.get(offer_id) if offer_id else None
            if offer is None:
                continue
            out.append({
                "campaign_type": item.get("campaign_type") or "retention",
                "name": item.get("name") or offer["name"],
                "objective": item.get("objective") or offer.get("description"),
                "audience": item.get("audience") or f"Customers in {zip_code}",
                "behaviour_basis": item.get("behaviour_basis") or [],
                "offer_id": offer["offer_id"],
                "offer_name": offer["name"],
                "channel": item.get("channel") or offer.get("channel"),
                "priority": int(item.get("priority") or index + 1),
                "suggested_by": "ai",
            })
        return out or drafts
    except Exception:  # noqa: BLE001
        return drafts


def enrich_profile_with_behaviour(
    profile: dict,
    zip_rows: list[dict],
    *,
    offers: list[dict] | None = None,
    use_ai_campaigns: bool = True,
) -> dict:
    menu = offers or load_offers()
    upsells = build_upsell_opportunities(zip_rows, offers=menu)
    if use_ai_campaigns:
        campaigns = suggest_campaigns_with_ai(
            zip_rows,
            zip_code=str(profile.get("zip_code")),
            city=profile.get("city"),
            upsells=upsells,
            risk_rate=profile.get("risk_rate"),
            business_impact_eur=profile.get("business_impact_eur"),
            offers=menu,
        )
    else:
        campaigns = build_campaign_drafts(
            zip_rows,
            zip_code=str(profile.get("zip_code")),
            city=profile.get("city"),
            upsells=upsells,
            offers=menu,
        )
    profile["upsell_opportunities"] = upsells
    # Gross yearly upsell (€/year) = customers × yearly ARPU uplift (pre take-rate).
    profile["upsell_yearly_eur"] = round(
        sum(float(item.get("yearly_upsell_eur") or 0.0) for item in upsells),
        2,
    )
    # Expected €/year after margin × take-rate (conservative).
    profile["upsell_potential_gain_eur"] = round(
        sum(float(item.get("potential_gain_eur") or 0.0) for item in upsells),
        2,
    )
    profile["upsell_potential_gain_period"] = "year"
    # Unique CLV pool of behaviour-eligible customers (distinct from expected gain).
    profile["upsell_clv_eur"] = upsell_addressable_clv_eur(zip_rows)
    profile["suggested_campaigns"] = annotate_campaign_explanations(campaigns, zip_rows, upsells)
    return profile
