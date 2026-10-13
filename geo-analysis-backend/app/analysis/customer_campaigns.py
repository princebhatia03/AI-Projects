"""Per-customer suggested offers/campaigns from churn problems + services."""

from __future__ import annotations

from typing import Any

from app.analysis.customer_services import service_match_needles
from app.analysis.offers import fallback_offer, load_offers, match_offers


RETENTION_OFFERS = {
    "OFF_PREVENT",
    "OFF_PRICE",
    "OFF_CONTRACT",
    "OFF_SENIOR",
    "OFF_BUNDLE",
    "OFF_DEVICE",
}


def _factor_codes(risk_factors: list[dict] | None) -> list[str]:
    codes: list[str] = []
    for factor in risk_factors or []:
        code = factor.get("code") if isinstance(factor, dict) else None
        if code:
            codes.append(str(code))
    return codes


def _factor_weight_map(risk_factors: list[dict] | None) -> dict[str, float]:
    weights: dict[str, float] = {}
    for factor in risk_factors or []:
        if not isinstance(factor, dict) or not factor.get("code"):
            continue
        code = str(factor["code"]).lower()
        weight = factor.get("weight")
        try:
            numeric = float(weight) if weight is not None else 0.5
        except (TypeError, ValueError):
            numeric = 0.5
        weights[code] = max(weights.get(code, 0.0), numeric)
    return weights


def _factor_labels(risk_factors: list[dict] | None, codes: list[str]) -> list[str]:
    by_code = {
        str(f.get("code")): str(f.get("label") or f.get("code"))
        for f in (risk_factors or [])
        if isinstance(f, dict) and f.get("code")
    }
    return [by_code.get(code, code) for code in codes]


def _resolution_text(
    offer: dict,
    matched_labels: list[str],
    *,
    churn_score: Any = None,
    services: dict | None = None,
) -> str:
    name = offer.get("name") or offer.get("offer_id") or "Offer"
    description = (offer.get("description") or "").strip()
    parts: list[str] = []
    if isinstance(churn_score, (int, float)) and not isinstance(churn_score, bool):
        parts.append(f"churn score {int(churn_score)}/100")
    active = [s.get("name") for s in (services or {}).get("active") or [] if s.get("name")]
    missing = list((services or {}).get("missing") or [])
    if active:
        parts.append("has " + ", ".join(active[:4]))
    if missing:
        parts.append("missing " + ", ".join(missing[:3]))
    if matched_labels:
        parts.append("problem: " + ", ".join(matched_labels[:3]))
    why = "; ".join(parts) if parts else "retention risk"
    base = f"Recommend {name} ({why})."
    if description:
        return f"{base} {description}"
    return base


# Offers that only make sense for a specific service gap. Others are compatible
# with any high-risk customer.
_SERVICE_FIT = {
    "OFF_UNLIM": lambda services: bool(services.get("internet_service")) and not services.get("unlimited_data"),
    "OFF_GB_BOOST": lambda services: bool(services.get("internet_service")) and not services.get("unlimited_data"),
    "OFF_FIBER": lambda services: bool(services.get("internet_service")),
    "OFF_WIFI": lambda services: bool(services.get("internet_service")),
    "OFF_HOME": lambda services: bool(services.get("phone_service")) and not services.get("internet_service"),
    "OFF_PROTECT": lambda services: bool(services.get("internet_service")) and not services.get("online_security"),
    "OFF_SUPPORT": lambda services: bool(services.get("internet_service")) and not services.get("premium_tech_support"),
}


def confidence_level(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


# Tags that mean the same problem. Used so "churn_score" and "high_churn_score"
# count as one hit, and so a broad offer is not treated as a perfect fit just
# because it lists the generic churn tag.
_TAG_GROUPS = (
    frozenset({"high_churn_score", "high_risk", "churn_score", "risk_rate", "risk_score_mean"}),
    frozenset({"price_sensitivity", "monthly_charge"}),
    frozenset({"low_satisfaction", "satisfaction_mean", "satisfaction_score"}),
    frozenset({"contract_month_to_month", "contract"}),
    frozenset({
        "heavy_usage_no_unlimited",
        "unlimited_data",
        "avg_monthly_gb",
        "extra_data_charges",
        "total_extra_data_charges",
    }),
    frozenset({"no_security_addon", "online_security"}),
    frozenset({"no_tech_support", "premium_tech_support"}),
    frozenset({"phone_only_no_internet", "internet_service"}),
    frozenset({"internet_type", "fiber", "competitor_speed"}),
    frozenset({"dependents", "number_of_dependents"}),
    frozenset({"tenure_months", "short_tenure"}),
)

_CATALOG_TAGS: dict[str, set[str]] | None = None


def _tag_group(code: str) -> frozenset[str]:
    for group in _TAG_GROUPS:
        if code in group:
            return group
    return frozenset({code})


def _catalog_tags(offer_id: str) -> set[str] | None:
    global _CATALOG_TAGS
    if _CATALOG_TAGS is None:
        from app.analysis.offers import load_offers

        _CATALOG_TAGS = {
            str(offer["offer_id"]): {
                str(tag).lower() for tag in (offer.get("addresses_patterns") or []) if tag
            }
            for offer in load_offers()
        }
    tags = _CATALOG_TAGS.get(str(offer_id))
    return set(tags) if tags else None


def _offer_tags(offer: dict) -> set[str]:
    """Patterns this offer is built to solve.

    The offer catalog wins over stored ``matched_patterns``. Older suggestions
    stamped every offer with the customer's first risk code, which made them
    all look equally confident.
    """
    catalog = _catalog_tags(str(offer.get("offer_id") or ""))
    if catalog:
        return catalog
    patterns = offer.get("addresses_patterns") or []
    if not patterns:
        patterns = offer.get("matched_patterns") or []
    return {str(tag).lower() for tag in patterns if tag}


def _offer_addresses(offer: dict, code: str) -> bool:
    needle = str(code).lower()
    group = _tag_group(needle)
    return any(tag == needle or tag in group for tag in _offer_tags(offer))


def _specificity(offer: dict, risk_factors: list[dict] | None) -> float:
    """How much of this offer is about risks the customer actually has.

    An offer aimed only at this customer's problems scores 1. An offer that
    also targets unrelated problems scores lower, so it does not tie with the
    focused one.
    """
    tags = _offer_tags(offer)
    if not tags:
        return 0.0
    offer_groups = {_tag_group(tag) for tag in tags}
    factor_groups = {
        _tag_group(str(factor["code"]).lower())
        for factor in (risk_factors or [])
        if isinstance(factor, dict) and factor.get("code")
    }
    if not offer_groups or not factor_groups:
        return 0.0
    hits = offer_groups & factor_groups
    return len(hits) / len(offer_groups)


def _service_fit(offer: dict, services: dict | None) -> float:
    if not services:
        return 0.5
    check = _SERVICE_FIT.get(str(offer.get("offer_id") or ""))
    if check is None:
        return 1.0
    return 1.0 if check(services) else 0.0


def _data_completeness(risk_factors: list[dict] | None, services: dict | None) -> float:
    snapshot = services or {}
    checks = (
        bool(risk_factors),
        bool(services),
        snapshot.get("churn_score") is not None,
        snapshot.get("satisfaction_score") is not None,
        snapshot.get("monthly_charge") is not None or bool(snapshot.get("contract")),
    )
    return sum(1 for item in checks if item) / len(checks)


def score_suggestion_confidence(
    offer: dict,
    *,
    risk_factors: list[dict] | None,
    services: dict | None = None,
) -> dict[str, Any]:
    """How well this offer fits one customer, from 0 to 100.

    This is a fit score from the customer's risk factors, services, and graph
    evidence. It is not the embedding similarity used by graph search.
    """
    weights = _factor_weight_map(risk_factors)
    total = sum(weights.values())
    matched_weight = sum(weight for code, weight in weights.items() if _offer_addresses(offer, code))
    coverage = (matched_weight / total) if total else 0.0
    strongest = max(weights, key=weights.get) if weights else None
    strongest_match = 1.0 if strongest and _offer_addresses(offer, strongest) else 0.0
    specificity = _specificity(offer, risk_factors)
    service_fit = _service_fit(offer, services)
    completeness = _data_completeness(risk_factors, services)
    # Graph support is a small nudge, and only when the offer really matches a
    # risk. A flat bonus made every graph suggestion tie at the same score.
    graph_evidence = 1.0 if offer.get("suggested_by") == "graph" and coverage > 0 else 0.0
    raw = (
        0.35 * coverage
        + 0.20 * strongest_match
        + 0.25 * specificity
        + 0.10 * service_fit
        + 0.05 * completeness
        + 0.05 * graph_evidence
    )
    score = int(round(max(0.0, min(1.0, raw)) * 100))

    labels = {
        str(factor.get("code")): str(factor.get("label") or factor.get("code"))
        for factor in (risk_factors or [])
        if isinstance(factor, dict) and factor.get("code")
    }
    reasons: list[str] = []
    if strongest and strongest_match:
        reasons.append(f"Addresses the strongest risk factor: {labels.get(strongest, strongest)}")
    if weights:
        reasons.append(f"Covers {int(round(coverage * 100))}% of weighted risk factors")
    if specificity >= 0.8 and coverage > 0:
        reasons.append("Focused on risks this customer actually has")
    elif coverage > 0 and specificity < 0.6:
        reasons.append("Also aimed at risks this customer does not have")
    if graph_evidence:
        reasons.append("Supported by the customer problem graph")
    if service_fit == 0:
        reasons.append("Customer service mix does not fit this offer")
    elif service_fit == 1.0 and str(offer.get("offer_id") or "") in _SERVICE_FIT:
        reasons.append("Matches the customer's current services")
    if completeness < 0.6:
        reasons.append("Customer profile is missing signals used for this score")

    return {
        "confidence_score": score,
        "confidence_level": confidence_level(score),
        "confidence_reasons": reasons,
    }


def rank_offers_by_confidence(
    offers: list[dict],
    *,
    risk_factors: list[dict] | None,
    services: dict | None = None,
) -> list[dict[str, Any]]:
    """Attach confidence and put the best-fitting offer first."""
    ranked = [
        {
            **offer,
            **score_suggestion_confidence(offer, risk_factors=risk_factors, services=services),
        }
        for offer in offers
    ]
    ranked.sort(
        key=lambda offer: (
            int(offer.get("confidence_score") or 0),
            int(offer.get("match_score") or 0),
            -int(offer.get("priority") or 99),
        ),
        reverse=True,
    )
    explained: list[dict[str, Any]] = []
    for index, offer in enumerate(ranked, start=1):
        tags = sorted(_offer_tags(offer))
        explained.append({
            **offer,
            **explain_suggestion(
                {**offer, "addresses_patterns": tags},
                risk_factors=risk_factors,
                services=services,
            ),
            "addresses_patterns": tags,
            "rank": index,
        })
    return explained


def explain_suggestion(
    offer: dict,
    *,
    risk_factors: list[dict] | None,
    services: dict | None = None,
) -> dict[str, Any]:
    """Why this suggestion is shown, grounded in the customer's churn risk or service data."""
    relevant = [
        factor
        for factor in (risk_factors or [])
        if isinstance(factor, dict) and factor.get("code") and _offer_addresses(offer, str(factor["code"]))
    ]
    shown = relevant[:3]
    score = (services or {}).get("churn_score")
    churn_score = int(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None
    factor_bits = [
        str(factor.get("detail") or factor.get("label")).rstrip(".")
        for factor in shown
        if factor.get("detail") or factor.get("label")
    ]
    campaign_type = offer.get("campaign_type") or _campaign_type_for(
        offer.get("offer_id"),
        list(offer.get("matched_patterns") or []),
    )
    churn_risk = {
        "churn_score": churn_score,
        "factors": [
            {
                "code": factor.get("code"),
                "label": factor.get("label"),
                "detail": factor.get("detail"),
            }
            for factor in shown
        ],
    }
    if campaign_type == "upsell":
        if factor_bits:
            why = "Upsell because we found: " + "; ".join(factor_bits) + "."
        else:
            missing = [str(name) for name in ((services or {}).get("missing") or []) if name]
            if missing:
                why = "Upsell because the customer is missing " + ", ".join(missing[:3]) + "."
            else:
                why = "Upsell because the customer's services match this offer."
    elif churn_score is not None and factor_bits:
        why = (
            f"Shown because predicted churn risk is {churn_score}/100. "
            f"Risk found: {'; '.join(factor_bits)}."
        )
    elif churn_score is not None:
        why = (
            f"Predicted churn risk is {churn_score}/100, but this offer does not match "
            "a specific risk found for this customer."
        )
    elif factor_bits:
        why = "Shown because of churn risk: " + "; ".join(factor_bits) + "."
    else:
        why = "Shown because this customer is flagged as high churn risk."
    return {
        "why": why,
        "churn_risk": churn_risk,
        "evidence": factor_bits,
    }


def attach_suggestion_explanations(
    offers: list[dict],
    *,
    risk_factors: list[dict] | None,
    services: dict | None = None,
) -> list[dict[str, Any]]:
    explained: list[dict[str, Any]] = []
    for offer in offers:
        if offer.get("why") and offer.get("churn_risk"):
            explained.append(offer)
            continue
        explained.append({
            **offer,
            **explain_suggestion(offer, risk_factors=risk_factors, services=services),
        })
    return explained


def pick_highest_confidence_offer(offers: list[dict] | None) -> dict | None:
    """Offer to send when the caller does not pick one explicitly."""
    if not offers:
        return None
    return max(
        offers,
        key=lambda offer: (
            1 if offer.get("confidence_score") is not None else 0,
            int(offer.get("confidence_score") or 0),
            int(offer.get("match_score") or 0),
            -int(offer.get("rank") or 99),
        ),
    )


def _campaign_type_for(offer_id: str | None, matched: list[str]) -> str:
    if offer_id and offer_id in RETENTION_OFFERS:
        return "retention"
    problemish = {
        "high_churn_score",
        "high_risk",
        "low_satisfaction",
        "contract_month_to_month",
        "price_sensitivity",
        "short_tenure",
    }
    if any(str(code).lower() in problemish for code in matched):
        return "retention"
    return "upsell"


def build_suggested_offers(
    *,
    high_risk: bool,
    risk_factors: list[dict] | None,
    services: dict[str, Any] | None = None,
    offers: list[dict] | None = None,
    graph_offers: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """Ranked offers that best resolve the customer's Neo4j/problem signals.

    Walks risk factors strongest-first so the campaign fits the main pain
    point; service gaps only fill remaining slots. Optional ``graph_offers``
    from Neo4j ``HAS_RISK_FACTOR→ADDRESSED_BY`` are preferred when present.
    """
    if not high_risk:
        return []

    menu = offers or load_offers()
    by_id = {str(o["offer_id"]): o for o in menu}
    problem_weights = _factor_weight_map(risk_factors)
    codes = _factor_codes(risk_factors)
    service_needles = [
        str(n).lower()
        for n in service_match_needles(services)
        if str(n).lower() not in problem_weights
    ]

    graph_boost: dict[str, float] = {}
    graph_reason: dict[str, str] = {}
    graph_patterns: dict[str, list[str]] = {}
    for item in graph_offers or []:
        offer_id = str(item.get("offer_id") or "")
        if not offer_id or offer_id not in by_id:
            continue
        graph_boost[offer_id] = max(
            graph_boost.get(offer_id, 0.0),
            float(item.get("graph_score") or item.get("match_score") or 1.0),
        )
        if item.get("suggested_resolution") or item.get("reason"):
            graph_reason[offer_id] = str(
                item.get("suggested_resolution") or item.get("reason")
            )
        patterns = item.get("matched_patterns") or []
        if patterns:
            graph_patterns[offer_id] = [str(p) for p in patterns]

    ordered: list[dict] = []
    seen: set[str] = set()

    def _push(offer: dict, matched: list[str], *, score: float, source: str) -> None:
        offer_id = str(offer["offer_id"])
        if offer_id in seen:
            return
        seen.add(offer_id)
        ordered.append({
            **offer,
            "match_score": int(round(score)),
            "matched_patterns": matched,
            "_source": source,
        })

    # 1) Neo4j graph hits first (already grounded in customer problems).
    for offer_id, boost in sorted(graph_boost.items(), key=lambda kv: kv[1], reverse=True):
        offer = by_id[offer_id]
        matched = graph_patterns.get(offer_id) or [
            code for code in codes if _offer_addresses(offer, code)
        ]
        _push(offer, matched, score=20.0 + boost, source="graph")

    # 2) Strongest customer problem → best menu offer for that problem.
    factors_sorted = sorted(
        [f for f in (risk_factors or []) if isinstance(f, dict) and f.get("code")],
        key=lambda f: float(f.get("weight") or 0.5),
        reverse=True,
    )
    for index, factor in enumerate(factors_sorted):
        code = str(factor["code"])
        weight = float(factor.get("weight") or 0.5)
        for offer in match_offers([code], [], offers=menu):
            _push(
                offer,
                list(offer.get("matched_patterns") or [code]),
                score=15.0 + weight * 10.0 - index + float(offer.get("match_score") or 0),
                source="rules",
            )

    # 3) Remaining service-gap upsells (secondary).
    if service_needles:
        for offer in match_offers(service_needles, [], offers=menu):
            _push(
                offer,
                list(offer.get("matched_patterns") or service_needles[:1]),
                score=3.0 + float(offer.get("match_score") or 0),
                source="rules",
            )

    matches = ordered
    if not matches:
        needles = list(dict.fromkeys(codes + service_needles))
        matches = match_offers(needles, [], offers=menu)
        for offer in matches:
            offer["_source"] = "rules"
        if not matches:
            fallback = fallback_offer({"risk_rate": 0.3}, offers=menu)
            if not fallback:
                return []
            matches = [{
                **fallback,
                "match_score": 1,
                "matched_patterns": needles[:1] or ["high_churn_score"],
                "_source": "rules",
            }]

    churn_score = (services or {}).get("churn_score")
    out: list[dict[str, Any]] = []
    for index, offer in enumerate(matches, start=1):
        matched = list(offer.get("matched_patterns") or [])
        labels = _factor_labels(risk_factors, matched)
        source = offer.pop("_source", "rules")
        if str(offer["offer_id"]) in graph_boost:
            source = "graph"
        resolution = graph_reason.get(str(offer["offer_id"])) or _resolution_text(
            offer,
            labels,
            churn_score=churn_score,
            services=services,
        )
        out.append({
            "offer_id": offer["offer_id"],
            "offer_name": offer.get("name") or offer["offer_id"],
            "description": offer.get("description") or "",
            "channel": offer.get("channel") or "",
            "priority": int(offer.get("priority") or 99),
            "match_score": int(offer.get("match_score") or 0),
            "rank": index,
            "matched_patterns": matched,
            "addresses_patterns": list(offer.get("addresses_patterns") or matched),
            "suggested_resolution": resolution,
            "suggested_by": source,
            "campaign_type": _campaign_type_for(offer.get("offer_id"), matched),
        })
    ranked = rank_offers_by_confidence(out, risk_factors=risk_factors, services=services)
    return attach_suggestion_explanations(ranked, risk_factors=risk_factors, services=services)


def build_suggested_campaign(suggested_offers: list[dict] | None) -> dict[str, Any] | None:
    """Compact primary campaign for UI Trigger display."""
    if not suggested_offers:
        return None
    top = suggested_offers[0]
    offer_name = top.get("offer_name") or top.get("name") or top.get("offer_id")
    return {
        "offer_id": top.get("offer_id"),
        "offer_name": offer_name,
        "name": offer_name,
        "campaign_type": top.get("campaign_type") or _campaign_type_for(
            top.get("offer_id"),
            list(top.get("matched_patterns") or []),
        ),
        "channel": top.get("channel") or "",
        "objective": top.get("suggested_resolution") or top.get("description") or "",
        "behaviour_basis": list(top.get("matched_patterns") or []),
        "priority": int(top.get("priority") or 1),
        "match_score": int(top.get("match_score") or 0),
        "confidence_score": top.get("confidence_score"),
        "confidence_level": top.get("confidence_level"),
        "confidence_reasons": list(top.get("confidence_reasons") or []),
        "why": top.get("why") or "",
        "churn_risk": top.get("churn_risk") or {},
        "evidence": list(top.get("evidence") or []),
        "suggested_by": top.get("suggested_by") or "rules",
        "suggested_resolution": top.get("suggested_resolution") or "",
    }
