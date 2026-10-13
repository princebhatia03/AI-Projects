"""ADK FunctionTools for the predictive risk / pincode pipeline."""

from __future__ import annotations

import json

from app import config
from app.analysis.diagnosis import diagnose_many, diagnose_pincode
from app.analysis.local_dataset import load_from_dataset, preview_from_rows
from app.analysis.offers import load_offers
from app.analysis.pattern_catalog import (
    assert_profiles_have_risk_rates,
    resolve_catalog,
    validate_catalog,
)
from app.analysis.pincode_aggregate import aggregate_by_pincode
from app.pipeline import state as pipeline_state
from app.storage import pincode_graph as graph

# Module-level working set for a pipeline run
_ROWS: list[dict] = []
_META: dict = {}
_CATALOG: dict | None = None
_PROFILES: list[dict] = []
_OFFERS: list[dict] = []
_DIAGNOSES: dict[str, dict] = {}


def tool_load_from_dataset() -> str:
    """Read telco CSVs from the local DataSet folder and join customer rows."""
    global _ROWS, _META
    rows, files, meta = load_from_dataset()
    _ROWS = rows
    _META = meta
    return json.dumps({"ok": True, "files": files, "row_count": len(rows), "directory": meta["directory"]})


def tool_preview_sample(limit: int = 8) -> str:
    """Return column names and a small anonymized sample of loaded rows."""
    if not _ROWS:
        return json.dumps({"error": "No rows loaded. Call load_from_dataset first."})
    return json.dumps(preview_from_rows(_ROWS, limit=limit))


def tool_list_columns() -> str:
    """List canonical column names after join."""
    if not _ROWS:
        return json.dumps({"error": "No rows loaded."})
    return json.dumps({"columns": sorted(_ROWS[0].keys())})


def tool_validate_catalog(catalog_json: str) -> str:
    """Validate a predictive risk pattern catalog JSON string against loaded columns."""
    global _CATALOG
    try:
        raw = json.loads(catalog_json)
        columns = sorted(_ROWS[0].keys()) if _ROWS else None
        _CATALOG = validate_catalog(raw, columns)
        return json.dumps({"ok": True, "catalog": _CATALOG})
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"ok": False, "error": str(exc)})


def tool_resolve_catalog() -> str:
    """Build a catalog via model when the LLM is ready, else the default catalog."""
    global _CATALOG
    if not _ROWS:
        return json.dumps({"error": "No rows loaded."})
    preview = preview_from_rows(_ROWS, limit=8)
    _CATALOG = resolve_catalog(preview["columns"], preview["sample"])
    return json.dumps({"ok": True, "source": _CATALOG.get("source"), "catalog": _CATALOG})


def tool_run_pincode_aggregation() -> str:
    """Run deterministic pandas aggregation for every pincode using the catalog."""
    global _PROFILES
    if not _ROWS:
        return json.dumps({"error": "No rows loaded."})
    if not _CATALOG:
        return json.dumps({"error": "No catalog. Call resolve_catalog or validate_catalog first."})
    _PROFILES = aggregate_by_pincode(_ROWS, _CATALOG)
    try:
        assert_profiles_have_risk_rates(_PROFILES)
    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    return json.dumps({
        "ok": True,
        "pincode_count": len(_PROFILES),
        "top_zips": [
            {
                "zip_code": p["zip_code"],
                "city": p.get("city"),
                "gap_score": p.get("gap_score"),
                "risk_rate": p.get("risk_rate"),
            }
            for p in _PROFILES[:10]
        ],
    })


def tool_load_offers() -> str:
    """Load the static offers menu from the local CSV."""
    global _OFFERS
    _OFFERS = load_offers()
    return json.dumps({"ok": True, "offers": _OFFERS})


def tool_write_pincode_graph() -> str:
    """Write all pincode profiles, customers, metrics, patterns, and offers into Neo4j."""
    if not _PROFILES:
        return json.dumps({"error": "No profiles. Run aggregation first."})
    offers = _OFFERS or load_offers()
    # Full dataset: every aggregated zip + customer cards for State→City→Zip→Customer.
    graph_profiles = list(_PROFILES)
    try:
        summary = graph.write_pincode_graph(graph_profiles, offers, clear=True)
        summary["graph_profile_count"] = len(graph_profiles)
        return json.dumps({"ok": True, **summary})
    except Exception as exc:  # noqa: BLE001
        # Keep pipeline alive for pandas/artifacts when Neo4j is down
        return json.dumps({"ok": True, "neo4j_skipped": True, "error": str(exc)})


def tool_get_pincode_profile(zip_code: str) -> str:
    """Return the aggregate profile for one zip code."""
    for profile in _PROFILES:
        if str(profile["zip_code"]) == str(zip_code):
            return json.dumps(profile)
    stored = pipeline_state.get_profile(zip_code)
    if stored:
        return json.dumps(stored)
    return json.dumps({"error": f"No profile for {zip_code}"})


def tool_diagnose_top_pincodes(top_n: int = 0) -> str:
    """Diagnose top pincodes and assign offers from the menu; persist to Neo4j."""
    global _DIAGNOSES
    if not _PROFILES:
        return json.dumps({"error": "No profiles."})
    offers = _OFFERS or load_offers()
    limit = top_n or config.DIAGNOSIS_TOP_N
    _DIAGNOSES = diagnose_many(_PROFILES, top_n=limit, offers=offers)
    try:
        graph.attach_diagnoses(_DIAGNOSES)
        neo_ok = True
        neo_error = None
    except Exception as exc:  # noqa: BLE001
        neo_ok = False
        neo_error = str(exc)
    return json.dumps({
        "ok": True,
        "diagnosed": len(_DIAGNOSES),
        "neo4j": neo_ok,
        "neo4j_error": neo_error,
        "sample": list(_DIAGNOSES.values())[:3],
    })


def tool_attach_diagnosis(diagnosis_json: str) -> str:
    """Persist one diagnosis JSON onto the Neo4j graph."""
    try:
        diagnosis = json.loads(diagnosis_json)
        graph.attach_diagnosis(diagnosis)
        _DIAGNOSES[str(diagnosis["zip_code"])] = diagnosis
        return json.dumps({"ok": True, "zip_code": diagnosis["zip_code"]})
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"ok": False, "error": str(exc)})


def tool_neo4j_graphrag_search(question: str, top_k: int = 5) -> str:
    """Semantic GraphRAG search over pincode metrics, patterns, diagnoses, and offers."""
    try:
        hits = graph.graphrag_search(question, top_k=top_k)
        return json.dumps({"ok": True, "hits": hits})
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"ok": False, "error": str(exc)})


def tool_persist_pipeline_state() -> str:
    """Save catalog, profiles, diagnoses, and meta into artifacts and memory."""
    offers = _OFFERS or load_offers()
    pipeline_state.save_pipeline(
        rows=_ROWS,
        catalog=_CATALOG or {},
        profiles=_PROFILES,
        offers=offers,
        diagnoses=_DIAGNOSES,
        meta=_META,
    )
    return json.dumps({"ok": True, "artifacts": str(pipeline_state.artifacts_dir())})


def tool_get_high_risk_customer_facts(zip_code: str, customer_id: str) -> str:
    """Return facts for one high-risk customer. No LLM — used by customer_risk_agent."""
    from app.analysis.business_impact import churn_probability, contract_type, mask_customer_id
    from app.analysis.customer_risk import explain_customer_risk

    row = _find_customer_row(zip_code, customer_id)
    if row:
        probability = churn_probability(row)
        high_risk = row.get("high_risk") == "Yes" or probability >= 0.65
        if not high_risk:
            return json.dumps({
                "ok": False,
                "error": "Customer is not high risk — agent only runs for churn-risk customers",
            })
        explanation = explain_customer_risk(row)
        return json.dumps({
            "ok": True,
            "zip_code": str(zip_code),
            "customer_id": row.get("customer_id"),
            "customer_ref": mask_customer_id(row.get("customer_id")),
            "high_risk": True,
            "contract_type": contract_type(row),
            "contract": row.get("contract"),
            "churn_score": row.get("churn_score"),
            "churn_probability": round(probability, 3),
            "satisfaction_score": row.get("satisfaction_score"),
            "tenure_months": row.get("tenure_months"),
            "monthly_charge": row.get("monthly_charge"),
            "phone_service": row.get("phone_service"),
            "internet_service": row.get("internet_service"),
            "unlimited_data": row.get("unlimited_data"),
            "online_security": row.get("online_security"),
            "premium_tech_support": row.get("premium_tech_support"),
            "risk_factors": explanation.get("risk_factors") or [],
        })

    profile = None
    for item in _PROFILES:
        if str(item.get("zip_code")) == str(zip_code):
            profile = item
            break
    if profile is None:
        profile = pipeline_state.get_profile(zip_code)
    card = None
    for item in (profile or {}).get("customers_detail") or []:
        if item.get("customer_id") == customer_id or item.get("customer_ref") == customer_id:
            card = item
            break
    if not card:
        return json.dumps({"ok": False, "error": "Customer not found in this pincode"})
    if not card.get("high_risk"):
        return json.dumps({
            "ok": False,
            "error": "Customer is not high risk — agent only runs for churn-risk customers",
        })
    return json.dumps({
        "ok": True,
        "zip_code": str(zip_code),
        "customer_id": card.get("customer_id"),
        "customer_ref": card.get("customer_ref"),
        "high_risk": True,
        "contract_type": card.get("contract_type"),
        "churn_probability": card.get("churn_probability"),
        "churn_score": int(round(float(card.get("churn_probability") or 0) * 100)),
        "satisfaction_score": card.get("satisfaction_score"),
        "tenure_months": card.get("tenure_months"),
        "monthly_charge": card.get("monthly_charge_eur"),
        "risk_factors": card.get("risk_factors") or [],
    })


def tool_save_customer_risk_why(
    zip_code: str,
    customer_id: str,
    risk_why: str,
) -> str:
    """Persist the ADK customer_risk_agent narrative onto the customer card."""
    text = (risk_why or "").strip()
    if not text:
        return json.dumps({"ok": False, "error": "risk_why is empty"})
    facts_raw = tool_get_high_risk_customer_facts(zip_code, customer_id)
    facts = json.loads(facts_raw)
    if not facts.get("ok"):
        return facts_raw
    updated = pipeline_state.update_customer_risk_why(
        zip_code,
        str(facts.get("customer_id") or customer_id),
        risk_why=text,
        risk_factors=facts.get("risk_factors") or [],
        risk_why_source="adk_agent",
    )
    if not updated:
        return json.dumps({"ok": False, "error": "Could not update customer card"})
    return json.dumps({
        "ok": True,
        "customer_id": facts.get("customer_id"),
        "customer_ref": facts.get("customer_ref"),
        "risk_why": text,
        "risk_why_source": "adk_agent",
        "risk_factors": facts.get("risk_factors") or [],
        "high_risk": True,
    })


# Backward-compatible alias used by older agent instructions.
def tool_explain_high_risk_customer(zip_code: str, customer_id: str, use_agent: bool = True) -> str:
    """Alias: fetch high-risk customer facts for the ADK customer_risk_agent."""
    return tool_get_high_risk_customer_facts(zip_code, customer_id)


def _find_customer_row(zip_code: str, customer_id: str) -> dict | None:
    for row in _ROWS:
        if str(row.get("zip_code")) != str(zip_code):
            continue
        if str(row.get("customer_id")) == str(customer_id):
            return row
    # Also search persisted rows in pipeline state.
    for row in pipeline_state.get_rows():
        if str(row.get("zip_code")) != str(zip_code):
            continue
        if str(row.get("customer_id")) == str(customer_id):
            return row
    return None


def working_snapshot() -> dict:
    return {
        "rows": _ROWS,
        "meta": _META,
        "catalog": _CATALOG,
        "profiles": _PROFILES,
        "offers": _OFFERS,
        "diagnoses": _DIAGNOSES,
    }
