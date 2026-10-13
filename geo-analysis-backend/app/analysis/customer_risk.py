"""Per-customer churn risk explanations (deterministic + optional LLM polish)."""

from __future__ import annotations

import json
from typing import Any

from app import config


def _risk_factors(row: dict) -> list[dict[str, Any]]:
    """Ranked friction signals that explain predicted churn for one customer."""
    factors: list[dict[str, Any]] = []
    score = row.get("churn_score")
    sat = row.get("satisfaction_score")
    contract = str(row.get("contract") or "")
    tenure = row.get("tenure_months")
    monthly = row.get("monthly_charge")
    gb = row.get("avg_monthly_gb")

    if isinstance(score, (int, float)) and not isinstance(score, bool) and score >= config.HIGH_RISK_SCORE:
        factors.append({
            "code": "high_churn_score",
            "label": "High predictive risk score",
            "detail": f"Risk score {int(score)}/100 is at or above the leave threshold ({config.HIGH_RISK_SCORE}).",
            "weight": min(1.0, float(score) / 100.0),
        })

    if isinstance(sat, (int, float)) and not isinstance(sat, bool) and sat <= config.LOW_SATISFACTION:
        factors.append({
            "code": "low_satisfaction",
            "label": "Low satisfaction",
            "detail": f"Satisfaction {int(sat)}/5 is critically low — experience friction before they leave.",
            "weight": 0.9 if sat <= 1 else 0.75,
        })

    if "month" in contract.lower():
        factors.append({
            "code": "contract_month_to_month",
            "label": "Month-to-month contract",
            "detail": "Flexible contract — easier to switch providers without lock-in.",
            "weight": 0.7,
        })

    if (
        row.get("internet_service") == "Yes"
        and row.get("unlimited_data") == "No"
        and isinstance(gb, (int, float))
        and gb >= 40
    ):
        factors.append({
            "code": "heavy_usage_no_unlimited",
            "label": "Heavy data use without unlimited",
            "detail": f"Avg {gb:.0f} GB/month on a metered plan — overage / friction risk.",
            "weight": 0.65,
        })

    if row.get("internet_service") == "Yes" and row.get("online_security") == "No":
        factors.append({
            "code": "no_security_addon",
            "label": "No online security addon",
            "detail": "Internet without security protection — common upsell / risk gap.",
            "weight": 0.45,
        })

    if row.get("internet_service") == "Yes" and row.get("premium_tech_support") == "No":
        factors.append({
            "code": "no_tech_support",
            "label": "No premium tech support",
            "detail": "Missing support cover — unresolved issues can push leave intent.",
            "weight": 0.45,
        })

    if row.get("phone_service") == "Yes" and row.get("internet_service") == "No":
        factors.append({
            "code": "phone_only_no_internet",
            "label": "Phone-only (no home internet)",
            "detail": "Phone-only household — weaker product stickiness versus bundled peers.",
            "weight": 0.4,
        })

    if isinstance(tenure, (int, float)) and not isinstance(tenure, bool) and tenure <= 6:
        factors.append({
            "code": "short_tenure",
            "label": "Short tenure",
            "detail": f"Only {int(tenure)} months with us — early-life churn risk is elevated.",
            "weight": 0.55,
        })

    if (
        isinstance(monthly, (int, float))
        and not isinstance(monthly, bool)
        and monthly >= 80
        and isinstance(sat, (int, float))
        and sat <= 3
    ):
        factors.append({
            "code": "price_sensitivity",
            "label": "Price pressure",
            "detail": f"High monthly charge (€{monthly:.0f}) with weak satisfaction — price is a leave driver.",
            "weight": 0.6,
        })

    factors.sort(key=lambda item: item.get("weight") or 0.0, reverse=True)
    return factors[:5]


def explain_customer_risk(row: dict, *, polished: str | None = None) -> dict[str, Any]:
    """Build a short why-at-risk summary for one customer.

    Only high-risk / medium-high probability customers get a full narrative;
    low-risk customers get an empty explanation.
    """
    from app.analysis.business_impact import churn_probability

    probability = churn_probability(row)
    high_risk = row.get("high_risk") == "Yes" or probability >= 0.65
    factors = _risk_factors(row) if (high_risk or probability >= 0.40) else []

    if not high_risk and probability < 0.40:
        return {
            "risk_why": None,
            "risk_factors": [],
            "risk_why_source": None,
        }

    if polished and polished.strip():
        return {
            "risk_why": polished.strip(),
            "risk_factors": factors,
            "risk_why_source": "agent",
        }

    if not factors:
        if high_risk:
            why = (
                f"Predicted high leave risk (score {row.get('churn_score')}) "
                "with no single dominant service gap — prioritize a retention check-in."
            )
        else:
            why = "Moderate leave risk — monitor satisfaction and contract flexibility."
        return {
            "risk_why": why,
            "risk_factors": factors,
            "risk_why_source": "rules",
        }

    top = factors[0]
    extras = [f["label"] for f in factors[1:3]]
    why = top["detail"]
    if extras:
        why = f"{why} Also: {', '.join(extras).lower()}."
    return {
        "risk_why": why,
        "risk_factors": factors,
        "risk_why_source": "rules",
    }


def polish_risk_why_with_llm(row: dict, factors: list[dict]) -> str | None:
    """Optional one-customer narrative via the configured LLM. High-risk only."""
    polish_risk_why_with_llm.last_error = None  # type: ignore[attr-defined]
    if not config.llm_ready():
        polish_risk_why_with_llm.last_error = (  # type: ignore[attr-defined]
            f"LLM is not configured (LLM_PROVIDER={config.LLM_PROVIDER})"
        )
        return None
    from app.analysis.business_impact import churn_probability, contract_type, mask_customer_id

    probability = churn_probability(row)
    high_flag = row.get("high_risk") in {"Yes", True, "true", "TRUE"}
    if not high_flag and probability < 0.65:
        polish_risk_why_with_llm.last_error = "Customer is not high risk"  # type: ignore[attr-defined]
        return None

    facts = {
        "customer_ref": mask_customer_id(row.get("customer_id")),
        "contract_type": contract_type(row),
        "contract": row.get("contract"),
        "churn_score": row.get("churn_score"),
        "satisfaction_score": row.get("satisfaction_score"),
        "tenure_months": row.get("tenure_months"),
        "monthly_charge": row.get("monthly_charge"),
        "internet_service": row.get("internet_service"),
        "phone_service": row.get("phone_service"),
        "unlimited_data": row.get("unlimited_data"),
        "online_security": row.get("online_security"),
        "premium_tech_support": row.get("premium_tech_support"),
        "factors": [{"code": f["code"], "label": f["label"], "detail": f["detail"]} for f in factors],
    }
    prompt = (
        "You are a telco retention analyst. The customer is still active but predicted to churn. "
        "In 1-2 short sentences, explain WHY they are at risk using ONLY the JSON facts. "
        "Do not invent metrics. Do not mention gender. Be concrete and sales-usable.\n\n"
        f"FACTS:\n{json.dumps(facts)}"
    )
    try:
        import litellm
        from litellm import completion

        config.apply_litellm_env()
        # Some models reject custom temperature while reasoning is active.
        litellm.drop_params = True
        response = completion(
            model=config.litellm_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=1,
            max_completion_tokens=220,
            **config.litellm_call_kwargs(),
        )
        text = (response.choices[0].message.content or "").strip()
        return text or None
    except Exception as exc:  # noqa: BLE001
        # Stash last error for API/tool callers to surface.
        polish_risk_why_with_llm.last_error = str(exc)  # type: ignore[attr-defined]
        return None


def explain_high_risk_customer(
    row: dict,
    *,
    use_agent: bool = True,
) -> dict[str, Any]:
    """Explain one high-risk customer via the agent when requested.

    When use_agent=True, only an LLM narrative is returned (no rules fallback text).
    """
    from app.analysis.business_impact import churn_probability

    probability = churn_probability(row)
    high_risk = row.get("high_risk") == "Yes" or probability >= 0.65
    base = explain_customer_risk(row)
    if not high_risk:
        return {**base, "ok": False, "error": "Customer is not high risk"}
    if not use_agent:
        return {**base, "ok": True}
    if not config.llm_ready():
        return {
            "ok": False,
            "error": f"Customer-risk agent needs LLM configured (LLM_PROVIDER={config.LLM_PROVIDER})",
            "risk_why": None,
            "risk_factors": base.get("risk_factors") or [],
            "risk_why_source": None,
        }
    polished = polish_risk_why_with_llm(row, base.get("risk_factors") or [])
    if not polished:
        detail = getattr(polish_risk_why_with_llm, "last_error", None)
        return {
            "ok": False,
            "error": detail or "Customer-risk agent could not produce an explanation",
            "risk_why": None,
            "risk_factors": base.get("risk_factors") or [],
            "risk_why_source": None,
        }
    return {**explain_customer_risk(row, polished=polished), "ok": True}
