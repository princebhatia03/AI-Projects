"""In-memory + artifact persistence for the agentic pipeline."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app import config

_lock = threading.Lock()
_STATE: dict[str, Any] = {
    "status": {
        "loaded": False,
        "running": False,
        "chat_ready": False,
        "agentic": True,
        "postgres_required": False,
    },
    "catalog": None,
    "profiles": [],
    "offers": [],
    "diagnoses": {},
    "meta": {},
    "rows": [],
    "campaigns": [],
}


def artifacts_dir() -> Path:
    path = Path(config.ARTIFACTS_DIR)
    if not path.is_absolute():
        path = config.ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_status() -> dict:
    with _lock:
        status = dict(_STATE["status"])
        status["pincode_count"] = len(_STATE["profiles"])
        status["diagnosis_count"] = len(_STATE["diagnoses"])
        status.update(_STATE.get("meta") or {})
        return status


def set_running(running: bool) -> None:
    with _lock:
        _STATE["status"]["running"] = running
        if not running:
            _STATE["status"].pop("stage", None)
            _STATE["status"].pop("progress", None)


def set_progress(stage: str, *, step: int | None = None, total: int | None = None) -> None:
    """Expose the current pipeline stage for /pipeline/status while a run is active."""
    with _lock:
        _STATE["status"]["running"] = True
        _STATE["status"]["stage"] = stage
        if step is not None and total is not None:
            _STATE["status"]["progress"] = {
                "step": step,
                "total": total,
                "label": stage,
                "percent": round(100.0 * step / total, 1) if total else 0.0,
            }
        else:
            _STATE["status"]["progress"] = {"label": stage}


def save_pipeline(
    *,
    rows: list[dict],
    catalog: dict,
    profiles: list[dict],
    offers: list[dict],
    diagnoses: dict[str, dict],
    meta: dict,
) -> None:
    from app.storage import campaigns_db

    with _lock:
        _STATE["rows"] = rows
        _STATE["catalog"] = catalog
        _STATE["profiles"] = profiles
        _STATE["offers"] = offers
        _STATE["diagnoses"] = diagnoses
        _STATE["meta"] = meta
        _STATE["status"] = {
            "loaded": True,
            "running": False,
            "chat_ready": config.llm_ready(),
            "llm_provider": config.LLM_PROVIDER,
            "agentic": True,
            "postgres_required": False,
            "error": None,
        }

    campaigns = campaigns_db.list_campaigns(limit=200)
    with _lock:
        _STATE["campaigns"] = campaigns

    root = artifacts_dir()
    (root / "pattern_catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    (root / "pincode_profiles.json").write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    (root / "diagnoses.json").write_text(json.dumps(diagnoses, indent=2), encoding="utf-8")
    (root / "offers.json").write_text(json.dumps(offers, indent=2), encoding="utf-8")
    (root / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (root / "campaigns.json").write_text(json.dumps(campaigns, indent=2), encoding="utf-8")


def set_error(message: str) -> None:
    with _lock:
        _STATE["status"]["running"] = False
        _STATE["status"]["error"] = message
        _STATE["status"].pop("stage", None)
        _STATE["status"].pop("progress", None)


def get_catalog() -> dict | None:
    with _lock:
        return _STATE["catalog"]


def get_profiles() -> list[dict]:
    with _lock:
        return list(_STATE["profiles"])


def get_profile(zip_code: str) -> dict | None:
    with _lock:
        for profile in _STATE["profiles"]:
            if str(profile["zip_code"]) == str(zip_code):
                diagnosis = _STATE["diagnoses"].get(str(zip_code))
                hydrated = _hydrate_customer_campaigns({**profile, "diagnosis": diagnosis})
                hydrated = _hydrate_upsell_clv(hydrated)
                zip_rows = [
                    row
                    for row in (_STATE.get("rows") or [])
                    if str(row.get("zip_code")) == str(zip_code)
                ]
                return _hydrate_action_explanations(hydrated, zip_rows)
        return None


def _hydrate_upsell_clv(profile: dict) -> dict:
    """Ensure upsell CLV / expected gain are present for older artifacts."""
    opportunities = profile.get("upsell_opportunities") or []
    if not isinstance(opportunities, list) or not opportunities:
        return profile
    out = profile
    if out.get("upsell_potential_gain_eur") is None:
        out = {
            **out,
            "upsell_potential_gain_eur": round(
                sum(float(item.get("potential_gain_eur") or 0.0) for item in opportunities),
                2,
            ),
        }
    if out.get("upsell_yearly_eur") is None:
        yearly = 0.0
        for item in opportunities:
            if item.get("yearly_upsell_eur") is not None:
                yearly += float(item.get("yearly_upsell_eur") or 0.0)
            elif item.get("yearly_uplift_eur") is not None:
                yearly += float(item.get("customers") or 0) * float(item["yearly_uplift_eur"])
            elif item.get("monthly_uplift_eur") is not None:
                yearly += float(item.get("customers") or 0) * float(item["monthly_uplift_eur"]) * 12.0
        out = {
            **out,
            "upsell_yearly_eur": round(yearly, 2),
            "upsell_potential_gain_period": out.get("upsell_potential_gain_period") or "year",
        }
    if out.get("upsell_clv_eur") is None:
        # Prefer unique CLV when row-level data is still in memory.
        zip_code = str(out.get("zip_code") or "")
        zip_rows = [
            row
            for row in (_STATE.get("rows") or [])
            if str(row.get("zip_code")) == zip_code
        ]
        if zip_rows:
            from app.analysis.behaviour_actions import upsell_addressable_clv_eur

            out = {**out, "upsell_clv_eur": upsell_addressable_clv_eur(zip_rows)}
        else:
            out = {
                **out,
                "upsell_clv_eur": round(
                    sum(float(item.get("addressable_clv_eur") or 0.0) for item in opportunities),
                    2,
                ),
            }
    return out


def _hydrate_action_explanations(profile: dict, zip_rows: list[dict]) -> dict:
    """Fill why / evidence on stored upsells and area campaign suggestions."""
    from app.analysis.behaviour_actions import (
        annotate_campaign_explanations,
        signal_facts,
    )

    changed = False
    opportunities = [dict(item) for item in (profile.get("upsell_opportunities") or [])]
    facts = signal_facts(zip_rows) if zip_rows else {}
    rules = {}
    if any(not item.get("why") or not item.get("evidence") for item in opportunities):
        from app.analysis.behaviour_actions import UPSELL_RULES, _upsell_why

        rules = {rule["signal"]: rule for rule in UPSELL_RULES}
    next_upsells: list[dict] = []
    for item in opportunities:
        if item.get("why") and item.get("evidence"):
            next_upsells.append(item)
            continue
        signal = str(item.get("signal") or "")
        fact = facts.get(signal)
        rule = rules.get(signal)
        if fact and rule:
            item["why"] = _upsell_why(rule, fact)
            item["evidence"] = list(fact.get("evidence") or [])
            item["evidence_detail"] = fact.get("detail") or {}
        else:
            customers = int(item.get("customers") or 0)
            reason = str(item.get("reason") or "This service gap showed up in the pincode").rstrip(".")
            item["evidence"] = item.get("evidence") or [
                f"{customers} customers in this pincode match {signal.replace('_', ' ') or 'this pattern'}"
            ]
            item["why"] = item.get("why") or f"{item['evidence'][0]}. {reason}."
        next_upsells.append(item)
        changed = True

    campaigns = [dict(item) for item in (profile.get("suggested_campaigns") or [])]
    if campaigns and any(not item.get("why") for item in campaigns):
        if zip_rows:
            campaigns = annotate_campaign_explanations(campaigns, zip_rows, next_upsells)
        else:
            for item in campaigns:
                if item.get("why"):
                    continue
                if item.get("campaign_type") == "upsell":
                    match = next(
                        (entry for entry in next_upsells if entry.get("offer_id") == item.get("offer_id")),
                        None,
                    )
                    item["why"] = (match or {}).get("why") or item.get("objective") or ""
                    item["evidence"] = list((match or {}).get("evidence") or [])
                else:
                    audience = item.get("audience") or "high-risk customers"
                    item["why"] = f"{item.get('objective') or 'Retention suggestion'}. Audience: {audience}."
                    item["churn_risk"] = item.get("churn_risk") or {"evidence": [audience]}
                    item["evidence"] = item.get("evidence") or [audience]
        changed = True

    if not changed:
        return profile
    return {**profile, "upsell_opportunities": next_upsells, "suggested_campaigns": campaigns}


def _hydrate_customer_campaigns(profile: dict) -> dict:
    """Ensure each high-risk card exposes suggested_campaign for the UI Trigger column."""
    from app.analysis.customer_campaigns import (
        attach_suggestion_explanations,
        build_suggested_campaign,
        build_suggested_offers,
        rank_offers_by_confidence,
    )

    cards = profile.get("customers_detail")
    if not isinstance(cards, list) or not cards:
        return profile
    changed = False
    hydrated: list[dict] = []
    for card in cards:
        item = dict(card)
        if item.get("high_risk") and not item.get("suggested_offers"):
            item["suggested_offers"] = build_suggested_offers(
                high_risk=True,
                risk_factors=item.get("risk_factors") or [],
                services=item.get("services"),
            )
            changed = True
        offers = item.get("suggested_offers") or []
        # Rescore when confidence was never computed, or when the stored offer
        # has no catalog tags. Those rows all inherited the same risk code and
        # therefore the same confidence.
        if offers and any(
            offer.get("confidence_score") is None or not offer.get("addresses_patterns")
            for offer in offers
        ):
            item["suggested_offers"] = rank_offers_by_confidence(
                offers,
                risk_factors=item.get("risk_factors") or [],
                services=item.get("services"),
            )
            item["suggested_campaign"] = build_suggested_campaign(item["suggested_offers"])
            item["primary_offer_id"] = item["suggested_offers"][0].get("offer_id")
            changed = True
            offers = item["suggested_offers"]
        elif offers and any(not offer.get("why") or not offer.get("churn_risk") for offer in offers):
            item["suggested_offers"] = attach_suggestion_explanations(
                offers,
                risk_factors=item.get("risk_factors") or [],
                services=item.get("services"),
            )
            item["suggested_campaign"] = build_suggested_campaign(item["suggested_offers"])
            changed = True
        elif item.get("suggested_offers") and not item.get("suggested_campaign"):
            item["suggested_campaign"] = build_suggested_campaign(item["suggested_offers"])
            changed = True
        if item.get("suggested_offers") and not item.get("primary_offer_id"):
            item["primary_offer_id"] = item["suggested_offers"][0].get("offer_id")
            changed = True
        hydrated.append(item)
    if not changed:
        return profile
    return {**profile, "customers_detail": hydrated}


def list_briefing(include_thin: bool = False) -> list[dict]:
    with _lock:
        items = []
        for profile in _STATE["profiles"]:
            if profile.get("thin_sample") and not include_thin:
                continue
            diagnosis = _STATE["diagnoses"].get(str(profile["zip_code"])) or {}
            top = (profile.get("top_gaps") or [None])[0]
            hydrated = _hydrate_upsell_clv(profile)
            items.append({
                "zip_code": hydrated["zip_code"],
                "city": hydrated.get("city"),
                "state": hydrated.get("state"),
                "customers": hydrated.get("customers"),
                "risk_rate": hydrated.get("risk_rate"),
                "risk_baseline": hydrated.get("risk_baseline"),
                "risk_score_mean": hydrated.get("risk_score_mean"),
                "churn_rate": hydrated.get("risk_rate"),
                "churn_baseline": hydrated.get("risk_baseline"),
                "gap_score": hydrated.get("gap_score"),
                "problem": diagnosis.get("problem") or (top["label"] if top else "No dominant risk gap"),
                "city_value": top["value"] if top else hydrated.get("risk_rate"),
                "baseline_value": top["baseline"] if top else hydrated.get("risk_baseline"),
                "unit": top["unit"] if top else "share",
                "offer_id": diagnosis.get("offer_id"),
                "offer_name": diagnosis.get("offer_name"),
                "confidence": diagnosis.get("confidence"),
                "thin_sample": hydrated.get("thin_sample"),
                "business_impact_eur": hydrated.get("business_impact_eur"),
                "at_risk_clv_eur": hydrated.get("at_risk_clv_eur"),
                "total_clv_eur": hydrated.get("total_clv_eur"),
                "upsell_yearly_eur": hydrated.get("upsell_yearly_eur"),
                "upsell_potential_gain_eur": hydrated.get("upsell_potential_gain_eur"),
                "upsell_potential_gain_period": hydrated.get("upsell_potential_gain_period") or "year",
                "upsell_clv_eur": hydrated.get("upsell_clv_eur"),
                "high_risk_customers": hydrated.get("high_risk_customers"),
                "churn_by_contract": hydrated.get("churn_by_contract"),
                "currency": hydrated.get("currency") or "EUR",
            })
        return items


def get_offers() -> list[dict]:
    with _lock:
        return list(_STATE["offers"])


def get_diagnoses() -> dict[str, dict]:
    with _lock:
        return dict(_STATE["diagnoses"])


def get_campaigns(zip_code: str | None = None, limit: int = 100) -> list[dict]:
    from app.storage import campaigns_db

    return campaigns_db.list_campaigns(zip_code=zip_code, limit=limit)


def get_rows() -> list[dict]:
    with _lock:
        return list(_STATE.get("rows") or [])


def update_profile_actions(
    zip_code: str,
    *,
    upsell_opportunities: list[dict],
    suggested_campaigns: list[dict],
    customers_detail: list[dict] | None = None,
    upsell_potential_gain_eur: float | None = None,
    upsell_clv_eur: float | None = None,
    upsell_yearly_eur: float | None = None,
) -> dict | None:
    """Persist behaviour upsells + AI campaign suggestions onto a profile."""
    with _lock:
        profile = None
        profile_index = -1
        for index, item in enumerate(_STATE["profiles"]):
            if str(item.get("zip_code")) == str(zip_code):
                profile = item
                profile_index = index
                break
        if profile is None:
            return None
        profile = {
            **profile,
            "upsell_opportunities": upsell_opportunities,
            "suggested_campaigns": suggested_campaigns,
        }
        if upsell_yearly_eur is not None:
            profile["upsell_yearly_eur"] = upsell_yearly_eur
        elif upsell_opportunities and profile.get("upsell_yearly_eur") is None:
            profile["upsell_yearly_eur"] = round(
                sum(float(item.get("yearly_upsell_eur") or 0.0) for item in upsell_opportunities),
                2,
            )
        if upsell_potential_gain_eur is not None:
            profile["upsell_potential_gain_eur"] = upsell_potential_gain_eur
        elif upsell_opportunities and profile.get("upsell_potential_gain_eur") is None:
            profile["upsell_potential_gain_eur"] = round(
                sum(float(item.get("potential_gain_eur") or 0.0) for item in upsell_opportunities),
                2,
            )
        profile["upsell_potential_gain_period"] = "year"
        if upsell_clv_eur is not None:
            profile["upsell_clv_eur"] = upsell_clv_eur
        elif upsell_opportunities and profile.get("upsell_clv_eur") is None:
            # Fallback when unique CLV was not passed: sum per-signal pools (may overlap).
            profile["upsell_clv_eur"] = round(
                sum(float(item.get("addressable_clv_eur") or 0.0) for item in upsell_opportunities),
                2,
            )
        if customers_detail is not None:
            profile["customers_detail"] = customers_detail
        _STATE["profiles"][profile_index] = profile
        profiles_snapshot = list(_STATE["profiles"])
        diagnosis = _STATE["diagnoses"].get(str(zip_code))

    root = artifacts_dir()
    (root / "pincode_profiles.json").write_text(json.dumps(profiles_snapshot, indent=2), encoding="utf-8")
    return {**profile, "diagnosis": diagnosis}


def update_customer_risk_why(
    zip_code: str,
    customer_id: str,
    *,
    risk_why: str | None,
    risk_factors: list[dict] | None = None,
    risk_why_source: str | None = None,
) -> dict | None:
    """Patch risk explanation onto one customer card and persist profiles."""
    with _lock:
        profile = None
        profile_index = -1
        for index, item in enumerate(_STATE["profiles"]):
            if str(item.get("zip_code")) == str(zip_code):
                profile = item
                profile_index = index
                break
        if profile is None:
            return None

        cards = list(profile.get("customers_detail") or [])
        updated_card = None
        new_cards = []
        for card in cards:
            if card.get("customer_id") == customer_id or card.get("customer_ref") == customer_id:
                next_card = {
                    **card,
                    "risk_why": risk_why,
                    "risk_factors": risk_factors or card.get("risk_factors") or [],
                    "risk_why_source": risk_why_source,
                }
                updated_card = next_card
                new_cards.append(next_card)
            else:
                new_cards.append(card)
        if updated_card is None:
            return None
        profile = {**profile, "customers_detail": new_cards}
        _STATE["profiles"][profile_index] = profile
        profiles_snapshot = list(_STATE["profiles"])
        diagnosis = _STATE["diagnoses"].get(str(zip_code))

    root = artifacts_dir()
    (root / "pincode_profiles.json").write_text(json.dumps(profiles_snapshot, indent=2), encoding="utf-8")
    return {**profile, "diagnosis": diagnosis, "updated_customer": updated_card}


def trigger_campaign_for_zip(
    zip_code: str,
    *,
    customer_ids: list[str] | None = None,
    all_high_risk: bool = True,
    offer_id: str | None = None,
    risk_levels: list[str] | None = None,
) -> dict[str, Any]:
    """Mark customers in a zip as campaign-triggered and persist to SQLite.

    ``risk_levels`` (e.g. ``["High", "Medium"]``) targets every not-yet-triggered
    customer whose churn prediction is in that list.
    """
    from datetime import datetime, timezone
    from uuid import uuid4

    from app.analysis.business_impact import apply_campaign_status
    from app.analysis.customer_campaigns import pick_highest_confidence_offer
    from app.storage import campaigns_db

    with _lock:
        profile = None
        profile_index = -1
        for index, item in enumerate(_STATE["profiles"]):
            if str(item.get("zip_code")) == str(zip_code):
                profile = item
                profile_index = index
                break
        if profile is None:
            return {"ok": False, "error": f"No profile for {zip_code}"}

        cards = list(profile.get("customers_detail") or [])
        if not cards:
            return {"ok": False, "error": "No customer details for this pincode. Re-run prediction."}

        levels = {str(level).strip().lower() for level in (risk_levels or []) if str(level).strip()}
        if levels:
            from app.analysis.customer_campaigns import (
                build_suggested_campaign,
                build_suggested_offers,
            )

            prepared: list[dict] = []
            targeted: list[str] = []
            for card in cards:
                item = dict(card)
                level = str(item.get("churn_prediction") or "").lower()
                if level in levels and item.get("campaign_status") != "triggered":
                    if not item.get("suggested_offers"):
                        item["suggested_offers"] = build_suggested_offers(
                            high_risk=True,
                            risk_factors=item.get("risk_factors") or [],
                            services=item.get("services"),
                        )
                        item["suggested_campaign"] = build_suggested_campaign(item["suggested_offers"])
                        item["primary_offer_id"] = (
                            item["suggested_offers"][0]["offer_id"] if item["suggested_offers"] else None
                        )
                    item["campaign_eligible"] = True
                    targeted.append(str(item.get("customer_id")))
                prepared.append(item)
            if not targeted:
                return {"ok": False, "error": "No untriggered customers match the selected risk levels"}
            cards = prepared
            customer_ids = targeted
            all_high_risk = False

        campaign_id = f"CMP-{uuid4().hex[:8].upper()}"
        updated = apply_campaign_status(
            cards,
            customer_ids=customer_ids,
            all_high_risk=all_high_risk if not customer_ids else False,
            campaign_id=campaign_id,
        )
        triggered = [c for c in updated if c.get("campaign_id") == campaign_id]
        if not triggered:
            return {"ok": False, "error": "No eligible high-risk customers matched"}

        diagnosis_offer = (_STATE["diagnoses"].get(str(zip_code)) or {}).get("offer_id")
        assignments: list[dict[str, Any]] = []
        for card in triggered:
            chosen = None
            if offer_id:
                chosen = next(
                    (
                        item
                        for item in (card.get("suggested_offers") or [])
                        if item.get("offer_id") == offer_id
                    ),
                    None,
                )
                chosen_id = offer_id
            else:
                chosen = pick_highest_confidence_offer(card.get("suggested_offers") or [])
                chosen_id = (chosen or {}).get("offer_id") or card.get("primary_offer_id") or diagnosis_offer
            card["triggered_offer_id"] = chosen_id
            card["triggered_offer_name"] = (chosen or {}).get("offer_name") or (chosen or {}).get("name")
            card["triggered_confidence_score"] = (chosen or {}).get("confidence_score")
            card["triggered_confidence_level"] = (chosen or {}).get("confidence_level")
            assignments.append({
                "customer_id": card.get("customer_id"),
                "customer_ref": card.get("customer_ref"),
                "offer_id": chosen_id,
                "offer_name": card.get("triggered_offer_name"),
                "confidence_score": card.get("triggered_confidence_score"),
                "confidence_level": card.get("triggered_confidence_level"),
            })

        chosen_ids = {item.get("offer_id") for item in assignments if item.get("offer_id")}
        resolved_offer = next(iter(chosen_ids)) if len(chosen_ids) == 1 else None

        profile = {
            **profile,
            "customers_detail": updated,
        }
        _STATE["profiles"][profile_index] = profile
        record = {
            "campaign_id": campaign_id,
            "zip_code": str(zip_code),
            "city": profile.get("city"),
            "offer_id": resolved_offer,
            "selection": "explicit" if offer_id else "highest_confidence",
            "risk_levels": sorted(level.capitalize() for level in levels),
            "assignments": assignments,
            "customer_count": len(triggered),
            "clv_eur": round(sum(float(c.get("clv_eur") or 0) for c in triggered), 2),
            "customer_refs": [c.get("customer_ref") for c in triggered],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        profiles_snapshot = list(_STATE["profiles"])
        diagnosis = _STATE["diagnoses"].get(str(zip_code))

    campaigns_db.insert_campaign(record)
    with _lock:
        memory = list(_STATE.get("campaigns") or [])
        memory.insert(0, record)
        _STATE["campaigns"] = memory[:200]

    root = artifacts_dir()
    (root / "pincode_profiles.json").write_text(json.dumps(profiles_snapshot, indent=2), encoding="utf-8")
    # Keep a JSON mirror for debugging; SQLite is the source of truth for history.
    (root / "campaigns.json").write_text(
        json.dumps(campaigns_db.list_campaigns(limit=200), indent=2),
        encoding="utf-8",
    )
    return {"ok": True, "campaign": record, "profile": {**profile, "diagnosis": diagnosis}}


def load_artifacts_if_present() -> bool:
    root = artifacts_dir()
    catalog_path = root / "pattern_catalog.json"
    profiles_path = root / "pincode_profiles.json"
    if not catalog_path.exists() or not profiles_path.exists():
        return False
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    diagnoses = {}
    offers = []
    meta = {}
    if (root / "diagnoses.json").exists():
        diagnoses = json.loads((root / "diagnoses.json").read_text(encoding="utf-8"))
    if (root / "offers.json").exists():
        offers = json.loads((root / "offers.json").read_text(encoding="utf-8"))
    if (root / "meta.json").exists():
        meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
    legacy_campaigns = []
    if (root / "campaigns.json").exists():
        legacy_campaigns = json.loads((root / "campaigns.json").read_text(encoding="utf-8"))
    from app.storage import campaigns_db

    campaigns_db.init_db()
    if legacy_campaigns:
        campaigns_db.migrate_from_json(legacy_campaigns)
    campaigns = campaigns_db.list_campaigns(limit=200)
    # Avoid rewriting files on startup; hydrate memory only.
    with _lock:
        _STATE["rows"] = []
        _STATE["catalog"] = catalog
        _STATE["profiles"] = profiles
        _STATE["offers"] = offers
        _STATE["diagnoses"] = diagnoses
        _STATE["meta"] = meta
        _STATE["campaigns"] = campaigns
        _STATE["status"] = {
            "loaded": True,
            "running": False,
            "chat_ready": config.llm_ready(),
            "llm_provider": config.LLM_PROVIDER,
            "agentic": True,
            "postgres_required": False,
            "error": None,
            "from_artifacts": True,
        }
    return True
