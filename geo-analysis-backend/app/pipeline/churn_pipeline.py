"""Agentic churn pipeline: tools + optional ADK specialists."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app import config
from app.agents import churn_tools as tools
from app.pipeline import state as pipeline_state

logger = logging.getLogger(__name__)

_PIPELINE_STEPS: list[tuple[str, Any]] = [
    ("load_from_dataset", tools.tool_load_from_dataset),
    ("resolve_catalog", tools.tool_resolve_catalog),
    ("run_pincode_aggregation", tools.tool_run_pincode_aggregation),
    ("load_offers", tools.tool_load_offers),
    ("write_pincode_graph", tools.tool_write_pincode_graph),
    ("diagnose_top_pincodes", tools.tool_diagnose_top_pincodes),
    ("persist_pipeline_state", tools.tool_persist_pipeline_state),
]


def _step_summary(name: str, payload: dict) -> str:
    bits: list[str] = []
    for key in (
        "row_count",
        "pincode_count",
        "offer_count",
        "diagnosis_count",
        "files",
        "neo4j_skipped",
        "source",
        "ok",
    ):
        if key in payload and payload[key] is not None:
            bits.append(f"{key}={payload[key]}")
    if name == "persist_pipeline_state" and payload.get("artifacts"):
        bits.append(f"artifacts={payload['artifacts']}")
    return ", ".join(bits) if bits else "ok"


def run_pipeline_deterministic() -> dict[str, Any]:
    """Run the full pipeline by calling tools in fixed order (always works)."""
    total = len(_PIPELINE_STEPS)
    steps: list[dict] = []
    started = time.perf_counter()
    pipeline_state.set_running(True)
    pipeline_state.set_progress("starting", step=0, total=total)
    logger.info("Pipeline START — %s steps (deterministic)", total)
    try:
        for index, (name, fn) in enumerate(_PIPELINE_STEPS, start=1):
            pipeline_state.set_progress(name, step=index, total=total)
            logger.info("Pipeline [%s/%s] %s — starting", index, total, name)
            step_started = time.perf_counter()
            raw = fn()
            payload = json.loads(raw)
            elapsed = time.perf_counter() - step_started
            summary = _step_summary(name, payload)
            steps.append({"step": name, "result": {k: v for k, v in payload.items() if k != "catalog"}})
            if payload.get("ok") is False:
                logger.error(
                    "Pipeline [%s/%s] %s — FAILED in %.1fs (%s)",
                    index,
                    total,
                    name,
                    elapsed,
                    summary,
                )
                raise RuntimeError(f"{name} failed: {payload}")
            if payload.get("error") and not payload.get("ok") and not payload.get("neo4j_skipped"):
                logger.error(
                    "Pipeline [%s/%s] %s — FAILED in %.1fs (%s)",
                    index,
                    total,
                    name,
                    elapsed,
                    summary,
                )
                raise RuntimeError(f"{name} failed: {payload}")
            logger.info(
                "Pipeline [%s/%s] %s — done in %.1fs (%s)",
                index,
                total,
                name,
                elapsed,
                summary,
            )

        status = pipeline_state.get_status()
        total_elapsed = time.perf_counter() - started
        logger.info(
            "Pipeline COMPLETED successfully in %.1fs — pincodes=%s diagnoses=%s mode=deterministic_tools",
            total_elapsed,
            status.get("pincode_count"),
            status.get("diagnosis_count"),
        )
        return {"ok": True, "mode": "deterministic_tools", "steps": steps, "status": status}
    except Exception as exc:  # noqa: BLE001
        total_elapsed = time.perf_counter() - started
        logger.exception("Pipeline FAILED after %.1fs: %s", total_elapsed, exc)
        pipeline_state.set_error(str(exc))
        return {"ok": False, "error": str(exc), "steps": steps}
    finally:
        pipeline_state.set_running(False)


async def run_pipeline_agentic() -> dict[str, Any]:
    """Run ADK SequentialAgent specialists when LLM is ready; else deterministic tools."""
    if not config.llm_ready():
        logger.info(
            "Pipeline agentic skipped — LLM not ready (provider=%s); using deterministic tools",
            config.LLM_PROVIDER,
        )
        result = run_pipeline_deterministic()
        result["mode"] = f"deterministic_fallback_no_llm_{config.LLM_PROVIDER}"
        return result

    logger.info("Pipeline START — agentic ADK mode")
    pipeline_state.set_progress("agentic_adk", step=0, total=1)
    try:
        from app.agents.runtime import run_pipeline_agents

        agent_summary = await run_pipeline_agents()
        # Ensure artifacts exist even if agents skipped a tool
        snap = tools.working_snapshot()
        if not snap.get("profiles"):
            logger.warning("Agentic run produced no profiles — falling back to deterministic tools")
            return run_pipeline_deterministic() | {"agents": agent_summary, "mode": "agentic_then_tools"}
        tools.tool_persist_pipeline_state()
        status = pipeline_state.get_status()
        logger.info(
            "Pipeline COMPLETED successfully — agentic ADK; pincodes=%s diagnoses=%s",
            status.get("pincode_count"),
            status.get("diagnosis_count"),
        )
        return {
            "ok": True,
            "mode": "agentic_adk",
            "agents": agent_summary,
            "status": status,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Agentic pipeline error — falling back to deterministic tools: %s", exc)
        fallback = run_pipeline_deterministic()
        fallback["mode"] = "deterministic_after_agent_error"
        fallback["agent_error"] = str(exc)
        return fallback


def ask_graph(question: str) -> dict[str, Any]:
    """Semantic question over Neo4j via GraphRAG tool (+ optional LLM synthesis)."""
    raw = tools.tool_neo4j_graphrag_search(question, top_k=6)
    hits_payload = json.loads(raw)
    hits = hits_payload.get("hits") or []
    answer = None
    if config.llm_ready() and hits:
        try:
            answer = _synthesize_answer(question, hits)
        except Exception as exc:  # noqa: BLE001
            answer = f"(synthesis unavailable: {exc})"
    elif hits:
        top = hits[0]
        answer = top.get("sentence") or top.get("text") or json.dumps(top)
    else:
        answer = "No matching area facts found in Neo4j."
    return {"question": question, "hits": hits, "answer": answer}


def _synthesize_answer(question: str, hits: list[dict]) -> str:
    config.apply_litellm_env()
    from litellm import completion

    response = completion(
        model=config.litellm_model(),
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a sales area analyst. Answer using only the GraphRAG hits. "
                    "Cite zip codes and metrics from hits. Do not invent numbers or offers."
                ),
            },
            {"role": "user", "content": json.dumps({"question": question, "hits": hits})},
        ],
        temperature=0.2,
        **config.litellm_call_kwargs(),
    )
    return response.choices[0].message.content or ""
