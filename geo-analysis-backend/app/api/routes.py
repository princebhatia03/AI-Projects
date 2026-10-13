import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import config
from app.pipeline import state as pipeline_state
from app.pipeline.churn_pipeline import ask_graph, run_pipeline_deterministic
from app.storage import pincode_graph as graph

logger = logging.getLogger(__name__)
router = APIRouter()


class AskRequest(BaseModel):
    question: str = Field(min_length=2)


class PipelineRunRequest(BaseModel):
    mode: str = Field(default="auto", pattern="^(auto|deterministic|agentic)$")


class CampaignRequest(BaseModel):
    """Trigger a retention campaign for high-risk customers in a pincode.

    Omit ``offer_id`` to send each customer their highest-confidence suggestion.
    ``risk_levels`` (High / Medium / Low) targets every untriggered customer at those levels.
    """

    all_high_risk: bool = True
    customer_ids: list[str] = Field(default_factory=list)
    offer_id: str | None = None
    risk_levels: list[str] = Field(default_factory=list)


class CustomerExplainRequest(BaseModel):
    """Ask the customer-risk agent (or rules) why one high-risk customer may churn."""

    use_agent: bool = True


@router.get("/pipeline/status")
@router.get("/data/status")
def pipeline_status(request: Request):
    status = pipeline_state.get_status()
    status["chat_ready"] = config.llm_ready()
    status["llm_provider"] = config.LLM_PROVIDER
    if getattr(request.app.state, "load_error", None):
        status["error"] = request.app.state.load_error
    return status


@router.get("/patterns")
def patterns():
    catalog = pipeline_state.get_catalog()
    if catalog is None:
        raise HTTPException(status_code=404, detail="No pattern catalog stored")
    return catalog


@router.get("/pincodes")
@router.get("/scorecard")
def pincodes(include_thin: bool = False):
    places = pipeline_state.list_briefing(include_thin=include_thin)
    if not places:
        try:
            places = [
                {
                    "zip_code": row.get("zip_code"),
                    "city": row.get("city"),
                    "state": row.get("state"),
                    "customers": row.get("customers"),
                    "risk_rate": row.get("risk_rate"),
                    "risk_baseline": row.get("risk_baseline"),
                    "risk_score_mean": row.get("risk_score_mean"),
                    "churn_rate": row.get("risk_rate") or row.get("churn_rate"),
                    "churn_baseline": row.get("risk_baseline") or row.get("churn_baseline"),
                    "gap_score": row.get("gap_score"),
                    "problem": row.get("problem") or "No risk prediction yet",
                    "city_value": row.get("risk_rate") or row.get("churn_rate"),
                    "baseline_value": row.get("risk_baseline") or row.get("churn_baseline"),
                    "unit": "share",
                    "offer_id": row.get("offer_id"),
                    "offer_name": row.get("offer_name"),
                    "confidence": row.get("confidence"),
                    "thin_sample": row.get("thin_sample"),
                }
                for row in graph.list_pincodes(include_thin=include_thin)
            ]
        except Exception:
            places = []
    return {"places": places}


@router.get("/pincode/{zip_code}")
def pincode_detail(zip_code: str):
    profile = pipeline_state.get_profile(zip_code)
    if profile:
        return profile
    try:
        stored = graph.get_pincode(zip_code)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Neo4j unavailable: {exc}") from exc
    if not stored:
        raise HTTPException(status_code=404, detail="No data for that pincode")
    return stored


@router.post("/pincode/{zip_code}/suggest-actions")
def suggest_actions(zip_code: str):
    """Refresh behaviour upsells + AI campaign suggestions for one pincode."""
    from app.analysis.behaviour_actions import enrich_profile_with_behaviour
    from app.analysis.offers import load_offers

    profile = pipeline_state.get_profile(zip_code)
    if not profile:
        raise HTTPException(status_code=404, detail="No data for that pincode")

    zip_rows = [
        row
        for row in pipeline_state.get_rows()
        if str(row.get("zip_code")) == str(zip_code)
    ]
    if not zip_rows:
        # Reconstruct minimal behaviour rows from stored customer cards.
        zip_rows = []
        for card in profile.get("customers_detail") or []:
            contract_type = card.get("contract_type")
            zip_rows.append({
                "customer_id": card.get("customer_id"),
                "high_risk": "Yes" if card.get("high_risk") else "No",
                "churn_score": int(round(float(card.get("churn_probability") or 0) * 100)),
                "satisfaction_score": card.get("satisfaction_score"),
                "low_satisfaction": "Yes" if (card.get("satisfaction_score") or 5) <= 2 else "No",
                "tenure_months": card.get("tenure_months"),
                "monthly_charge": card.get("monthly_charge_eur"),
                "cltv": card.get("clv_eur"),
                "phone_service": "Yes" if contract_type in {"Mobile", "Bundle"} else "No",
                "internet_service": "Yes" if contract_type in {"Fixed", "Bundle"} else "No",
                "unlimited_data": "No",
                "online_security": "No",
                "premium_tech_support": "No",
                "dependents": "No",
                "multiple_lines": "No",
                "contract": "Month-to-Month",
                "avg_monthly_gb": 50 if contract_type in {"Fixed", "Bundle"} else 0,
            })
            for factor in card.get("risk_factors") or []:
                code = factor.get("code")
                if code == "heavy_usage_no_unlimited":
                    zip_rows[-1]["unlimited_data"] = "No"
                    zip_rows[-1]["avg_monthly_gb"] = 80
                if code == "no_security_addon":
                    zip_rows[-1]["online_security"] = "No"
                    zip_rows[-1]["internet_service"] = "Yes"
                if code == "no_tech_support":
                    zip_rows[-1]["premium_tech_support"] = "No"
                    zip_rows[-1]["internet_service"] = "Yes"
                if code == "phone_only_no_internet":
                    zip_rows[-1]["phone_service"] = "Yes"
                    zip_rows[-1]["internet_service"] = "No"
                if code == "contract_month_to_month":
                    zip_rows[-1]["contract"] = "Month-to-Month"

    enriched = enrich_profile_with_behaviour(
        dict(profile),
        zip_rows,
        offers=load_offers(),
        use_ai_campaigns=True,
    )

    # Refresh per-customer campaigns from Neo4j problem intelligence
    # (Customer → HAS_RISK_FACTOR → ADDRESSED_BY → Offer).
    from app.analysis.customer_campaigns import (
        build_suggested_campaign,
        build_suggested_offers,
    )

    menu = load_offers()
    refreshed_cards = []
    for card in enriched.get("customers_detail") or []:
        card = dict(card)
        if not card.get("high_risk"):
            card["suggested_offers"] = []
            card["suggested_campaign"] = None
            card["primary_offer_id"] = None
            refreshed_cards.append(card)
            continue
        customer_id = str(card.get("customer_id") or "")
        graph_offers = []
        try:
            graph_offers = graph.suggest_offers_from_customer_problems(customer_id)
        except Exception:  # noqa: BLE001
            graph_offers = []
        suggested = build_suggested_offers(
            high_risk=True,
            risk_factors=card.get("risk_factors") or [],
            services=card.get("services"),
            offers=menu,
            graph_offers=graph_offers,
        )
        card["suggested_offers"] = suggested
        card["suggested_campaign"] = build_suggested_campaign(suggested)
        card["primary_offer_id"] = suggested[0]["offer_id"] if suggested else None
        if customer_id and suggested:
            try:
                graph.sync_customer_suggested_offers(customer_id, suggested)
            except Exception:  # noqa: BLE001
                pass
        refreshed_cards.append(card)
    enriched["customers_detail"] = refreshed_cards

    updated = pipeline_state.update_profile_actions(
        zip_code,
        upsell_opportunities=enriched.get("upsell_opportunities") or [],
        suggested_campaigns=enriched.get("suggested_campaigns") or [],
        customers_detail=refreshed_cards,
        upsell_potential_gain_eur=enriched.get("upsell_potential_gain_eur"),
        upsell_clv_eur=enriched.get("upsell_clv_eur"),
        upsell_yearly_eur=enriched.get("upsell_yearly_eur"),
    )
    return updated or enriched


@router.post("/pipeline/run")
def pipeline_run(body: PipelineRunRequest, request: Request):
    if pipeline_state.get_status().get("running"):
        raise HTTPException(status_code=409, detail="Pipeline already running")

    logger.info("POST /pipeline/run accepted — starting deterministic pipeline")
    result = run_pipeline_deterministic()
    request.app.state.status = result.get("status") or pipeline_state.get_status()
    request.app.state.load_error = None if result.get("ok") else result.get("error")
    if not result.get("ok"):
        logger.error("POST /pipeline/run failed: %s", result.get("error"))
        raise HTTPException(status_code=500, detail=result.get("error") or "pipeline failed")
    status = request.app.state.status or {}
    logger.info(
        "POST /pipeline/run finished OK — pincodes=%s diagnoses=%s",
        status.get("pincode_count"),
        status.get("diagnosis_count"),
    )
    return result


@router.post("/agent/ask")
def agent_ask(body: AskRequest):
    try:
        return ask_graph(body.question)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/offers")
def offers():
    items = pipeline_state.get_offers()
    if not items:
        from app.analysis.offers import load_offers

        items = load_offers()
    return {"offers": items}


@router.get("/campaigns")
def campaigns(zip_code: str | None = None, limit: int = 100):
    return {"campaigns": pipeline_state.get_campaigns(zip_code=zip_code, limit=limit)}


@router.post("/pincode/{zip_code}/campaign")
def trigger_campaign(zip_code: str, body: CampaignRequest):
    result = pipeline_state.trigger_campaign_for_zip(
        zip_code,
        customer_ids=body.customer_ids or None,
        all_high_risk=body.all_high_risk,
        offer_id=body.offer_id,
        risk_levels=body.risk_levels or None,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Campaign failed")
    return result


@router.post("/pincode/{zip_code}/customers/{customer_id}/explain")
async def explain_customer(zip_code: str, customer_id: str, body: CustomerExplainRequest | None = None):
    """Explain churn risk for one high-risk customer via Google ADK customer_risk_agent."""
    from app.agents.runtime import run_customer_risk_agent

    payload = body or CustomerExplainRequest()
    if not payload.use_agent:
        raise HTTPException(status_code=400, detail="Customer risk explanation requires the ADK agent")
    result = await run_customer_risk_agent(zip_code, customer_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Explain failed")
    if "profile" not in result:
        result["profile"] = pipeline_state.get_profile(zip_code)
    return result
