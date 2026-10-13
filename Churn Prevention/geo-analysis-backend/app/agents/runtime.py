"""Google ADK multi-agent app for pincode risk prediction + offer assignment."""

from __future__ import annotations

import json
import logging
from typing import Any

from app import config
from app.agents import churn_tools as tools

logger = logging.getLogger(__name__)


def _model():
    config.apply_litellm_env()
    from google.adk.models.lite_llm import LiteLlm

    return LiteLlm(model=config.litellm_model(), **config.litellm_call_kwargs())


def build_pipeline_app():
    """SequentialAgent: ingest → pattern → aggregate → graph → diagnose."""
    from google.adk.agents import Agent, SequentialAgent
    from google.adk.apps import App
    from google.adk.plugins import ReflectAndRetryToolPlugin

    model = _model()

    ingest_agent = Agent(
        name="ingest_agent",
        model=model,
        description="Loads telco CSVs from the local DataSet folder and previews columns.",
        instruction=(
            "Call load_from_dataset once, then preview_sample once. "
            "Treat every row as an active subscriber — nobody has churned yet. "
            "Summarize row count and columns in one short sentence."
        ),
        tools=[tools.tool_load_from_dataset, tools.tool_preview_sample, tools.tool_list_columns],
        output_key="ingest_summary",
    )

    pattern_agent = Agent(
        name="pattern_agent",
        model=model,
        description="Designs the predictive risk pattern catalog for pincode aggregation.",
        instruction=(
            "Call resolve_catalog. If you prefer a custom catalog, produce JSON and call validate_catalog. "
            "place_key must be zip_code. Prefer predictive outcomes (risk_score, satisfaction, high_risk) "
            "and service-gap drivers. Do not treat past churn labels as outcomes. "
            "Respond with the catalog source only."
        ),
        tools=[tools.tool_resolve_catalog, tools.tool_validate_catalog, tools.tool_preview_sample],
        output_key="catalog_summary",
    )

    aggregate_agent = Agent(
        name="aggregate_agent",
        model=model,
        description="Runs deterministic pincode aggregation and loads preventive offers.",
        instruction=(
            "Call run_pincode_aggregation, then load_offers, then write_pincode_graph. "
            "Do not invent rates. Report pincode_count."
        ),
        tools=[
            tools.tool_run_pincode_aggregation,
            tools.tool_load_offers,
            tools.tool_write_pincode_graph,
        ],
        output_key="aggregate_summary",
    )

    diagnosis_agent = Agent(
        name="diagnosis_agent",
        model=model,
        description="Predicts what is weak in top pincodes and assigns menu offers.",
        instruction=(
            "Call diagnose_top_pincodes. You may call neo4j_graphrag_search for context. "
            "Frame answers as predictions for still-active customers. "
            "Offers must come from the menu only. Then call persist_pipeline_state."
        ),
        tools=[
            tools.tool_diagnose_top_pincodes,
            tools.tool_neo4j_graphrag_search,
            tools.tool_get_pincode_profile,
            tools.tool_persist_pipeline_state,
        ],
        output_key="diagnosis_summary",
    )

    pipeline = SequentialAgent(
        name="churn_pipeline",
        description="HF ingest → risk catalog → pandas aggregate → Neo4j → predictive diagnosis.",
        sub_agents=[ingest_agent, pattern_agent, aggregate_agent, diagnosis_agent],
    )

    query_agent = Agent(
        name="query_agent",
        model=model,
        description="Answers sales questions about at-risk places using GraphRAG.",
        instruction=(
            "Use neo4j_graphrag_search and optionally get_pincode_profile. "
            "Answer with zip, predicted problem, evidence, and preventive offer from tool results only. "
            "Do not claim customers have already left."
        ),
        tools=[tools.tool_neo4j_graphrag_search, tools.tool_get_pincode_profile],
    )

    customer_risk_agent = Agent(
        name="customer_risk_agent",
        model=model,
        description="Explains why a single high-risk customer is predicted to churn.",
        instruction=(
            "You explain churn risk for ONE still-active high-risk customer.\n"
            "1) Call get_high_risk_customer_facts with the given zip_code and customer_id.\n"
            "2) If ok is false, stop and report the tool error.\n"
            "3) Using ONLY tool facts, write 1-2 short sales-usable sentences on why they may leave.\n"
            "4) Call save_customer_risk_why with that narrative (zip_code, customer_id, risk_why).\n"
            "5) Reply with only the narrative text. Do not invent metrics. Do not mention gender."
        ),
        tools=[
            tools.tool_get_high_risk_customer_facts,
            tools.tool_save_customer_risk_why,
            tools.tool_get_pincode_profile,
        ],
        output_key="customer_risk_why",
    )

    router = Agent(
        name="coordinator",
        model=model,
        description="Routes to the risk pipeline, query agent, or customer risk agent.",
        instruction=(
            "If the user asks to run, reload, or rebuild the pipeline, transfer to churn_pipeline. "
            "If the user asks why a specific customer may churn, transfer to customer_risk_agent. "
            "If the user asks about a place, risk, offer, or what is weak, transfer to query_agent. "
            "Do not invent numbers."
        ),
        sub_agents=[pipeline, query_agent, customer_risk_agent],
    )

    return App(
        name="geo_churn",
        root_agent=router,
        plugins=[ReflectAndRetryToolPlugin(max_retries=2)],
    )


async def run_pipeline_agents() -> dict[str, Any]:
    """Execute the ADK pipeline SequentialAgent via Runner."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from app.pipeline import state as pipeline_state

    logger.info("ADK pipeline agents — starting SequentialAgent run")
    pipeline_state.set_progress("adk_sequential_agent")

    app = build_pipeline_app()
    pipeline = None
    for agent in app.root_agent.sub_agents or []:
        if agent.name == "churn_pipeline":
            pipeline = agent
            break
    root = pipeline or app.root_agent

    session_service = InMemorySessionService()
    session = await session_service.create_session(state={}, app_name=app.name, user_id="pipeline")
    from google.adk.apps import App

    pipe_app = App(name="geo_churn_pipeline", root_agent=root)
    runner = Runner(app=pipe_app, session_service=session_service)

    content = types.Content(
        role="user",
        parts=[types.Part(text="Run the full pincode risk-prediction pipeline end to end.")],
    )
    texts: list[str] = []
    seen_agents: set[str] = set()
    async for event in runner.run_async(
        session_id=session.id,
        user_id="pipeline",
        new_message=content,
    ):
        author = getattr(event, "author", None) or getattr(event, "agent_name", None)
        if author and author not in seen_agents:
            seen_agents.add(author)
            pipeline_state.set_progress(f"adk:{author}")
            logger.info("ADK pipeline stage — agent=%s", author)
        if getattr(event, "content", None) and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "text", None):
                    texts.append(part.text)
    logger.info(
        "ADK pipeline agents — finished (%s events, agents=%s)",
        len(texts),
        ", ".join(sorted(seen_agents)) or "none",
    )
    return {"messages": texts[-5:], "count": len(texts), "agents": sorted(seen_agents)}


def run_query_agent(question: str) -> str:
    """Synchronous helper used by /agent/ask when ADK async is not required."""
    from app.pipeline.churn_pipeline import ask_graph

    result = ask_graph(question)
    return result.get("answer") or json.dumps(result.get("hits") or [])


async def run_customer_risk_agent(zip_code: str, customer_id: str) -> dict[str, Any]:
    """Run the Google ADK customer_risk_agent for one high-risk customer."""
    if not config.llm_ready():
        return {
            "ok": False,
            "error": f"Customer-risk agent needs LLM configured (LLM_PROVIDER={config.LLM_PROVIDER})",
        }

    from google.adk.apps import App
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from app.pipeline import state as pipeline_state

    # Fail fast before spending an ADK turn on a low-risk / missing customer.
    facts = json.loads(tools.tool_get_high_risk_customer_facts(zip_code, customer_id))
    if not facts.get("ok"):
        return {"ok": False, "error": facts.get("error") or "Customer facts unavailable"}

    full = build_pipeline_app()
    agent = None
    for child in full.root_agent.sub_agents or []:
        if child.name == "customer_risk_agent":
            agent = child
            break
    if agent is None:
        return {"ok": False, "error": "customer_risk_agent is not registered"}

    session_service = InMemorySessionService()
    app = App(name="geo_customer_risk", root_agent=agent)
    session = await session_service.create_session(
        state={},
        app_name=app.name,
        user_id="customer-risk",
    )
    runner = Runner(app=app, session_service=session_service)
    prompt = (
        f"Explain why customer_id={customer_id} in zip_code={zip_code} is predicted to churn. "
        "Use get_high_risk_customer_facts then save_customer_risk_why."
    )
    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    texts: list[str] = []
    try:
        async for event in runner.run_async(
            session_id=session.id,
            user_id="customer-risk",
            new_message=content,
        ):
            if getattr(event, "content", None) and event.content.parts:
                for part in event.content.parts:
                    if getattr(part, "text", None):
                        texts.append(part.text)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"ADK customer_risk_agent failed: {exc}"}

    profile = pipeline_state.get_profile(zip_code)
    card = None
    for item in (profile or {}).get("customers_detail") or []:
        if item.get("customer_id") == facts.get("customer_id") or item.get("customer_id") == customer_id:
            card = item
            break

    risk_why = (card or {}).get("risk_why") if card and card.get("risk_why_source") == "adk_agent" else None
    if not risk_why and texts:
        # Agent replied but skipped save — persist the final reply.
        risk_why = texts[-1].strip()
        pipeline_state.update_customer_risk_why(
            zip_code,
            str(facts.get("customer_id") or customer_id),
            risk_why=risk_why,
            risk_factors=facts.get("risk_factors") or [],
            risk_why_source="adk_agent",
        )
        profile = pipeline_state.get_profile(zip_code)

    if not risk_why:
        return {
            "ok": False,
            "error": "ADK customer_risk_agent did not return an explanation",
            "messages": texts[-3:],
        }

    return {
        "ok": True,
        "customer_id": facts.get("customer_id"),
        "customer_ref": facts.get("customer_ref"),
        "risk_why": risk_why,
        "risk_why_source": "adk_agent",
        "risk_factors": facts.get("risk_factors") or [],
        "high_risk": True,
        "profile": profile,
        "messages": texts[-3:],
    }
