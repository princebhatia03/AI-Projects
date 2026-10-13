"""Predict what is going wrong in a pincode and assign a preventive offer."""

from __future__ import annotations

import json
from typing import Any

from app import config
from app.analysis.offers import fallback_offer, load_offers, match_offer, offer_ids


def _metric_unit(method: str | None, value: float | None) -> str:
    if method == "mean":
        return "number"
    if value is not None and 0.0 <= abs(value) <= 1.0:
        return "share"
    return "number"


def _evidence_rows(profile: dict, strongest_pattern: dict | None) -> list[dict]:
    """Always build a non-empty friction table when any metrics exist."""
    rows: list[dict] = []
    seen: set[str] = set()

    def add(item: dict) -> None:
        key = str(item.get("metric") or item.get("label") or "")
        if not key or key in seen:
            return
        if item.get("value") is None or item.get("baseline") is None:
            return
        seen.add(key)
        rows.append({
            "metric": key,
            "label": item.get("label") or key,
            "value": item["value"],
            "baseline": item["baseline"],
            "delta": item.get("delta", float(item["value"]) - float(item["baseline"])),
            "n": item.get("n") or 0,
            "unit": item.get("unit") or _metric_unit(item.get("method"), item.get("value")),
        })

    if strongest_pattern:
        for item in strongest_pattern.get("metrics") or []:
            add(item)

    for item in profile.get("top_gaps") or []:
        add(item)

    # Prefer outcome risk metrics so the table is never blank for thin zips.
    for item in profile.get("metrics") or []:
        if item.get("kind") == "outcome":
            add(item)
    for item in profile.get("metrics") or []:
        if item.get("kind") != "outcome":
            add(item)
        if len(rows) >= 8:
            break

    return rows[:8]


def _match_needles(profile: dict, patterns: list[dict], strongest_pattern: dict | None) -> list[str]:
    needles: list[str] = []
    if strongest_pattern:
        needles.append(strongest_pattern["pattern_id"])
    for item in patterns:
        needles.append(item["pattern_id"])
    for item in (profile.get("top_gaps") or [])[:8]:
        metric = str(item.get("metric") or "")
        needles.append(metric)
        if ":" in metric:
            needles.append(metric.split(":", 1)[0])
        label = str(item.get("label") or "")
        if label:
            needles.append(label)
    risk = profile.get("risk_rate")
    if isinstance(risk, (int, float)) and risk >= 0.25:
        needles.extend(["high_risk", "high_churn_score", "risk_rate"])
    if profile.get("risk_score_mean") and float(profile["risk_score_mean"]) >= config.HIGH_RISK_SCORE:
        needles.extend(["high_churn_score", "risk_score_mean", "churn_score"])
    return needles


def diagnose_pincode(
    profile: dict,
    catalog: dict | None = None,
    offers: list[dict] | None = None,
    polish: bool = True,
) -> dict:
    menu = offers or load_offers()
    top_gaps = profile.get("top_gaps") or []
    patterns = sorted(
        profile.get("patterns") or [],
        key=lambda item: item.get("gap_score") or 0.0,
        reverse=True,
    )
    thin = bool(profile.get("thin_sample"))
    customers = int(profile.get("customers") or 0)

    strongest_pattern = patterns[0] if patterns else None
    strongest_gap = top_gaps[0] if top_gaps else None
    evidence = _evidence_rows(profile, strongest_pattern)

    needles = _match_needles(profile, patterns, strongest_pattern)
    offer = match_offer(needles, [], menu) or fallback_offer(profile, menu)

    if strongest_pattern and strongest_pattern.get("metrics"):
        evidence_metric = strongest_pattern["metrics"][0]
        problem = (
            f"{profile.get('city') or 'Zip'} {profile['zip_code']} is predicted at risk: "
            f"{strongest_pattern['description']} "
            f"({evidence_metric['metric']} {evidence_metric['value']:.3f} vs "
            f"{evidence_metric['baseline']:.3f} elsewhere)."
        )
    elif strongest_gap:
        problem = (
            f"{profile.get('city') or 'Zip'} {profile['zip_code']} shows a predictive gap on "
            f"{strongest_gap.get('label') or strongest_gap['metric']}: "
            f"{strongest_gap['value']:.3f} here vs "
            f"{strongest_gap['baseline']:.3f} in the rest of the state "
            f"(n={strongest_gap.get('n')})."
        )
    elif evidence:
        top = evidence[0]
        problem = (
            f"{profile.get('city') or 'Zip'} {profile['zip_code']} differs on "
            f"{top.get('label') or top['metric']}: {top['value']:.3f} here vs "
            f"{top['baseline']:.3f} elsewhere."
        )
    else:
        problem = (
            f"Zip {profile['zip_code']} has limited sample size; "
            f"watch risk score and service mix versus the state."
        )

    if thin or customers < config.MIN_N:
        confidence = "low"
    elif evidence and abs(float(evidence[0].get("delta") or 0)) >= config.SHARE_DELTA:
        confidence = "high"
    else:
        confidence = "medium"

    result = {
        "zip_code": str(profile["zip_code"]),
        "city": profile.get("city"),
        "problem": problem,
        "evidence": evidence,
        "confidence": confidence,
        "offer_id": offer["offer_id"] if offer else None,
        "offer_name": offer["name"] if offer else None,
        "offer_rationale": (
            f"Assigned because this area matches {', '.join(offer['addresses_patterns'][:3])}."
            if offer else "No menu offer available."
        ),
        "pattern_id": strongest_pattern["pattern_id"] if strongest_pattern else None,
        "secondary_offer_id": None,
    }

    if polish:
        polished = _polish_with_model(profile, result, menu, catalog)
        if polished:
            # Never let the model wipe evidence or offer to empty.
            if not polished.get("evidence"):
                polished["evidence"] = evidence
            if not polished.get("offer_id") and offer:
                polished["offer_id"] = offer["offer_id"]
                polished["offer_name"] = offer["name"]
            return polished
    return result


def _polish_with_model(profile: dict, draft: dict, menu: list[dict], catalog: dict | None) -> dict | None:
    if not config.llm_ready():
        return None
    config.apply_litellm_env()
    try:
        from litellm import completion
    except Exception:
        return None
    allowed = sorted(offer_ids(menu))
    payload = {
        "profile_summary": {
            "zip_code": profile.get("zip_code"),
            "city": profile.get("city"),
            "customers": profile.get("customers"),
            "risk_rate": profile.get("risk_rate"),
            "risk_score_mean": profile.get("risk_score_mean"),
            "top_gaps": (profile.get("top_gaps") or [])[:5],
            "patterns": (profile.get("patterns") or [])[:5],
            "thin_sample": profile.get("thin_sample"),
        },
        "draft": draft,
        "offers": menu,
        "allowed_offer_ids": allowed,
    }
    try:
        response = completion(
            model=config.litellm_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write predictive area diagnoses for still-active customers. "
                        "Nobody has churned yet — explain what is going wrong / at risk and which "
                        "preventive offer fits. Return JSON only with keys problem, evidence, "
                        "confidence, offer_id, offer_rationale, secondary_offer_id. "
                        "offer_id must be null or one of allowed_offer_ids. "
                        "Keep evidence non-empty when draft.evidence is non-empty. "
                        "Do not invent numbers; use profile_summary only."
                    ),
                },
                {"role": "user", "content": json.dumps(payload)},
            ],
            temperature=0.1,
            **config.litellm_call_kwargs(),
        )
        text = response.choices[0].message.content or ""
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(text)
        offer_id = parsed.get("offer_id")
        if offer_id not in allowed and offer_id is not None:
            offer_id = draft.get("offer_id")
        offer_name = next((item["name"] for item in menu if item["offer_id"] == offer_id), None)
        return {
            **draft,
            "problem": parsed.get("problem") or draft["problem"],
            "evidence": parsed.get("evidence") or draft["evidence"],
            "confidence": parsed.get("confidence") or draft["confidence"],
            "offer_id": offer_id,
            "offer_name": offer_name,
            "offer_rationale": parsed.get("offer_rationale") or draft["offer_rationale"],
            "secondary_offer_id": parsed.get("secondary_offer_id"),
            "source": "model",
        }
    except Exception:
        return None


def diagnose_many(
    profiles: list[dict],
    top_n: int | None = None,
    offers: list[dict] | None = None,
) -> dict[str, dict]:
    """Diagnose every pincode. LLM polish only the top-N by gap_score."""
    polish_limit = top_n if top_n is not None else config.DIAGNOSIS_TOP_N
    menu = offers or load_offers()
    out: dict[str, dict] = {}
    for index, profile in enumerate(profiles):
        diagnosis = diagnose_pincode(
            profile,
            offers=menu,
            polish=index < polish_limit,
        )
        out[str(profile["zip_code"])] = diagnosis
    return out
