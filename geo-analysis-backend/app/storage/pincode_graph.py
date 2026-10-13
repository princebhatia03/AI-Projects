"""Pincode-centric Neo4j graph with semantic sentences and vector indexes."""

from __future__ import annotations

import json

from neo4j import GraphDatabase

from app.analysis.customer_services import SERVICE_CATALOG, uses_rows_for_graph
from app.config import EMBED_DIM, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER
from app.storage.embeddings import embed

_driver = None

METRIC_INDEX = "metricpoint_embedding"
PATTERN_INDEX = "patternsignal_embedding"
DIAGNOSIS_INDEX = "diagnosis_embedding"
OFFER_INDEX = "offer_embedding"
PINCODE_INDEX = "pincode_embedding"
CUSTOMER_INDEX = "customer_embedding"


def driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    return _driver


def close() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def _ensure_indexes(session) -> None:
    for name, label in [
        (METRIC_INDEX, "MetricPoint"),
        (PATTERN_INDEX, "PatternSignal"),
        (DIAGNOSIS_INDEX, "Diagnosis"),
        (OFFER_INDEX, "Offer"),
        (PINCODE_INDEX, "Pincode"),
        (CUSTOMER_INDEX, "Customer"),
    ]:
        session.run(
            f"""
            CREATE VECTOR INDEX {name} IF NOT EXISTS
            FOR (n:{label}) ON (n.embedding)
            OPTIONS {{indexConfig: {{
                `vector.dimensions`: $dim,
                `vector.similarity_function`: 'cosine'
            }}}}
            """,
            dim=EMBED_DIM,
        )
    session.run("CREATE INDEX state_name IF NOT EXISTS FOR (s:State) ON (s.name)")
    session.run("CREATE INDEX city_name_state IF NOT EXISTS FOR (c:City) ON (c.name, c.state)")
    session.run("CREATE INDEX customer_id IF NOT EXISTS FOR (c:Customer) ON (c.customer_id)")
    session.run("CREATE INDEX service_name IF NOT EXISTS FOR (s:Service) ON (s.name)")
    session.run("CREATE INDEX risk_factor_code IF NOT EXISTS FOR (r:RiskFactor) ON (r.code)")
    session.run("CREATE INDEX contract_type_name IF NOT EXISTS FOR (c:ContractType) ON (c.name)")


def upsert_offers(offers: list[dict]) -> int:
    rows = []
    for offer in offers:
        sentence = (
            f"Offer {offer['offer_id']}: {offer['name']}. {offer.get('description', '')} "
            f"Addresses: {', '.join(offer.get('addresses_patterns') or [])}."
        )
        rows.append({
            "offer_id": offer["offer_id"],
            "name": offer["name"],
            "description": offer.get("description") or "",
            "tags": offer.get("addresses_patterns") or [],
            "channel": offer.get("channel") or "",
            "priority": int(offer.get("priority") or 99),
            "sentence": sentence,
            "embedding": embed(sentence),
        })
    with driver().session() as session:
        _ensure_indexes(session)
        session.run(
            """
            UNWIND $rows AS row
            MERGE (o:Offer {offer_id: row.offer_id})
            SET o.name = row.name,
                o.description = row.description,
                o.tags = row.tags,
                o.channel = row.channel,
                o.priority = row.priority,
                o.sentence = row.sentence,
                o.embedding = row.embedding
            """,
            rows=rows,
        )
    return len(rows)


def _customer_sentence(card: dict, zip_code: str, city: str, state: str) -> str:
    offers = card.get("suggested_offers") or []
    offer_ids = ", ".join(o.get("offer_id") for o in offers[:5] if o.get("offer_id")) or "none"
    services = card.get("services") or {}
    active = ", ".join(
        s.get("name") for s in (services.get("active") or []) if s.get("name")
    ) or "none"
    missing = ", ".join(services.get("missing") or []) or "none"
    factors = ", ".join(
        f.get("code") for f in (card.get("risk_factors") or []) if f.get("code")
    ) or "none"
    return (
        f"Customer {card.get('customer_ref')} in zip {zip_code}, {city}, {state}. "
        f"Churn score {card.get('churn_score')}/100, probability {card.get('churn_probability')}, "
        f"high_risk={bool(card.get('high_risk'))}, CLV EUR={card.get('clv_eur')}. "
        f"Services in use: {active}. Missing: {missing}. "
        f"Contract {services.get('contract') or card.get('contract_type')}. "
        f"Churn risk factors: {factors}. Suggested offers: {offer_ids}."
    )


def write_pincode_graph(profiles: list[dict], offers: list[dict], clear: bool = True) -> dict:
    upsert_offers(offers)
    pin_rows = []
    metric_rows = []
    pattern_rows = []
    customer_rows = []
    offer_edge_rows = []
    uses_rows: list[dict] = []
    risk_factor_rows: list[dict] = []
    contract_rows: list[dict] = []

    for profile in profiles:
        zip_code = str(profile["zip_code"])
        city = profile.get("city") or "Unknown"
        state = profile.get("state") or "Unknown"
        risk = profile.get("risk_rate")
        baseline = profile.get("risk_baseline")
        risk_mean = profile.get("risk_score_mean")
        sentence = (
            f"Zip {zip_code} in {city}, {state}. Active customers {profile.get('customers')}. "
            f"Predicted high-risk share {risk} vs state {baseline}. "
            f"Mean risk score {risk_mean}."
        )
        pin_rows.append({
            "zip": zip_code,
            "city": city,
            "state": state,
            "n": int(profile.get("customers") or 0),
            "population": profile.get("population"),
            "risk_rate": risk,
            "risk_baseline": baseline,
            "risk_score_mean": risk_mean,
            "churn_rate": risk,
            "churn_baseline": baseline,
            "thin": bool(profile.get("thin_sample")),
            "gap_score": float(profile.get("gap_score") or 0),
            "sentence": sentence,
            "embedding": embed(sentence),
        })
        for metric in profile.get("metrics") or []:
            if isinstance(metric.get("value"), dict):
                continue
            m_sentence = (
                f"Zip {zip_code} {city}. {metric.get('label')}: "
                f"{metric.get('value')} here, {metric.get('baseline')} elsewhere "
                f"(delta {metric.get('delta')}, n={metric.get('n')})."
            )
            metric_rows.append({
                "zip": zip_code,
                "metric": metric["metric"],
                "label": metric.get("label") or metric["metric"],
                "value": float(metric["value"]),
                "baseline": float(metric["baseline"]),
                "delta": float(metric["delta"]),
                "gap_score": float(metric.get("gap_score") or 0),
                "n": int(metric.get("n") or 0),
                "unit": metric.get("unit") or "share",
                "thin": bool(metric.get("thin_sample")),
                "sentence": m_sentence,
                "embedding": embed(m_sentence),
            })
        for pattern in profile.get("patterns") or []:
            p_sentence = (
                f"Zip {zip_code} pattern {pattern['pattern_id']}: {pattern.get('description')}. "
                f"Support n={pattern.get('n')}, gap_score={pattern.get('gap_score')}."
            )
            pattern_rows.append({
                "zip": zip_code,
                "pattern_id": pattern["pattern_id"],
                "description": pattern.get("description") or "",
                "n": int(pattern.get("n") or 0),
                "gap_score": float(pattern.get("gap_score") or 0),
                "thin": bool(pattern.get("thin_sample")),
                "metrics_json": json.dumps(pattern.get("metrics") or []),
                "sentence": p_sentence,
                "embedding": embed(p_sentence),
            })
        for card in profile.get("customers_detail") or []:
            customer_id = str(card.get("customer_id") or "").strip()
            if not customer_id:
                continue
            services = card.get("services") or {}
            c_sentence = _customer_sentence(card, zip_code, city, state)
            churn_score = card.get("churn_score")
            if churn_score is None and isinstance(services.get("churn_score"), (int, float)):
                churn_score = services.get("churn_score")
            customer_rows.append({
                "customer_id": customer_id,
                "customer_ref": card.get("customer_ref") or customer_id,
                "zip": zip_code,
                "city": city,
                "state": state,
                "high_risk": bool(card.get("high_risk")),
                "churn_probability": float(card.get("churn_probability") or 0),
                "churn_score": int(churn_score) if isinstance(churn_score, (int, float)) else None,
                "satisfaction_score": card.get("satisfaction_score"),
                "clv_eur": float(card.get("clv_eur") or 0),
                "contract_type": card.get("contract_type") or "",
                "campaign_status": card.get("campaign_status") or "",
                "primary_offer_id": card.get("primary_offer_id"),
                "services_json": json.dumps(services),
                "sentence": c_sentence,
                "embedding": embed(c_sentence),
            })
            uses_rows.extend(uses_rows_for_graph(customer_id, services))
            contract_name = services.get("contract") or card.get("contract_type")
            if contract_name:
                contract_rows.append({
                    "customer_id": customer_id,
                    "contract": str(contract_name),
                })
            for factor in card.get("risk_factors") or []:
                code = factor.get("code") if isinstance(factor, dict) else None
                if not code:
                    continue
                risk_factor_rows.append({
                    "customer_id": customer_id,
                    "code": str(code),
                    "label": factor.get("label") or code,
                    "detail": factor.get("detail") or "",
                    "weight": float(factor.get("weight") or 0),
                })
            if not card.get("high_risk"):
                continue
            for offer in card.get("suggested_offers") or []:
                offer_id = offer.get("offer_id")
                if not offer_id:
                    continue
                offer_edge_rows.append({
                    "customer_id": customer_id,
                    "offer_id": offer_id,
                    "rank": int(offer.get("rank") or 0),
                    "match_score": int(offer.get("match_score") or 0),
                    "confidence_score": offer.get("confidence_score"),
                    "confidence_level": offer.get("confidence_level") or "",
                    "reason": offer.get("suggested_resolution") or "",
                    "channel": offer.get("channel") or "",
                    "priority": int(offer.get("priority") or 99),
                })

    def _chunks(items: list, size: int = 200):
        for index in range(0, len(items), size):
            yield items[index : index + size]

    with driver().session() as session:
        if clear:
            session.run("MATCH (n) DETACH DELETE n")
        _ensure_indexes(session)

    upsert_offers(offers)

    with driver().session() as session:
        session.run(
            """
            UNWIND $names AS name
            MERGE (s:Service {name: name})
            """,
            names=list(SERVICE_CATALOG),
        )
        for chunk in _chunks(pin_rows, 250):
            session.run(
                """
                UNWIND $rows AS row
                MERGE (s:State {name: row.state})
                MERGE (c:City {name: row.city, state: row.state})
                MERGE (s)-[:HAS_CITY]->(c)
                MERGE (p:Pincode {zip: row.zip})
                SET p.city = row.city,
                    p.state = row.state,
                    p.n = row.n,
                    p.population = row.population,
                    p.risk_rate = row.risk_rate,
                    p.risk_baseline = row.risk_baseline,
                    p.risk_score_mean = row.risk_score_mean,
                    p.churn_rate = row.churn_rate,
                    p.churn_baseline = row.churn_baseline,
                    p.thin_sample = row.thin,
                    p.gap_score = row.gap_score,
                    p.sentence = row.sentence,
                    p.embedding = row.embedding
                MERGE (c)-[:HAS_ZIP]->(p)
                MERGE (p)-[:IN_CITY]->(c)
                """,
                rows=chunk,
            )

    # Keep graph lean: top gaps + patterns only (not every metric for every zip)
    slim_metrics = sorted(metric_rows, key=lambda row: abs(row.get("gap_score") or 0), reverse=True)[:4000]
    with driver().session() as session:
        for chunk in _chunks(slim_metrics, 150):
            session.run(
                """
                UNWIND $rows AS row
                MATCH (p:Pincode {zip: row.zip})
                CREATE (m:MetricPoint {
                    zip: row.zip,
                    metric: row.metric,
                    label: row.label,
                    value: row.value,
                    baseline: row.baseline,
                    delta: row.delta,
                    gap_score: row.gap_score,
                    n: row.n,
                    unit: row.unit,
                    thin_sample: row.thin,
                    sentence: row.sentence,
                    embedding: row.embedding
                })
                CREATE (p)-[:HAS_METRIC]->(m)
                """,
                rows=chunk,
            )

    with driver().session() as session:
        for chunk in _chunks(pattern_rows, 150):
            session.run(
                """
                UNWIND $rows AS row
                MATCH (p:Pincode {zip: row.zip})
                CREATE (s:PatternSignal {
                    zip: row.zip,
                    pattern_id: row.pattern_id,
                    description: row.description,
                    n: row.n,
                    gap_score: row.gap_score,
                    thin_sample: row.thin,
                    metrics_json: row.metrics_json,
                    sentence: row.sentence,
                    embedding: row.embedding
                })
                CREATE (p)-[:HAS_PATTERN]->(s)
                """,
                rows=chunk,
            )
        session.run(
            """
            MATCH (s:PatternSignal), (o:Offer)
            WHERE any(tag IN o.tags WHERE toLower(tag) = toLower(s.pattern_id)
               OR toLower(s.pattern_id) CONTAINS toLower(tag)
               OR toLower(tag) CONTAINS toLower(s.pattern_id))
            MERGE (s)-[:ADDRESSED_BY]->(o)
            """
        )

    with driver().session() as session:
        for chunk in _chunks(customer_rows, 200):
            session.run(
                """
                UNWIND $rows AS row
                MATCH (p:Pincode {zip: row.zip})
                MERGE (cust:Customer {customer_id: row.customer_id})
                SET cust.customer_ref = row.customer_ref,
                    cust.zip = row.zip,
                    cust.city = row.city,
                    cust.state = row.state,
                    cust.high_risk = row.high_risk,
                    cust.churn_probability = row.churn_probability,
                    cust.churn_score = row.churn_score,
                    cust.satisfaction_score = row.satisfaction_score,
                    cust.clv_eur = row.clv_eur,
                    cust.contract_type = row.contract_type,
                    cust.campaign_status = row.campaign_status,
                    cust.primary_offer_id = row.primary_offer_id,
                    cust.services_json = row.services_json,
                    cust.sentence = row.sentence,
                    cust.embedding = row.embedding
                MERGE (p)-[:HAS_CUSTOMER]->(cust)
                """,
                rows=chunk,
            )
        for chunk in _chunks(uses_rows, 250):
            session.run(
                """
                UNWIND $rows AS row
                MATCH (cust:Customer {customer_id: row.customer_id})
                MERGE (svc:Service {name: row.service})
                MERGE (cust)-[u:USES]->(svc)
                SET u.detail = row.detail,
                    u.avg_monthly_gb = row.avg_monthly_gb
                """,
                rows=chunk,
            )
        for chunk in _chunks(contract_rows, 250):
            session.run(
                """
                UNWIND $rows AS row
                MATCH (cust:Customer {customer_id: row.customer_id})
                MERGE (ct:ContractType {name: row.contract})
                MERGE (cust)-[:ON_CONTRACT]->(ct)
                """,
                rows=chunk,
            )
        for chunk in _chunks(risk_factor_rows, 250):
            session.run(
                """
                UNWIND $rows AS row
                MATCH (cust:Customer {customer_id: row.customer_id})
                MERGE (rf:RiskFactor {code: row.code})
                ON CREATE SET rf.label = row.label
                SET rf.label = coalesce(rf.label, row.label)
                MERGE (cust)-[hr:HAS_RISK_FACTOR]->(rf)
                SET hr.detail = row.detail,
                    hr.weight = row.weight
                """,
                rows=chunk,
            )
        # Link risk factors to offers that address them (campaign intelligence path).
        session.run(
            """
            MATCH (rf:RiskFactor), (o:Offer)
            WHERE any(tag IN o.tags WHERE toLower(tag) = toLower(rf.code)
               OR toLower(rf.code) CONTAINS toLower(tag)
               OR toLower(tag) CONTAINS toLower(rf.code))
            MERGE (rf)-[:ADDRESSED_BY]->(o)
            """
        )
        for chunk in _chunks(offer_edge_rows, 200):
            session.run(
                """
                UNWIND $rows AS row
                MATCH (cust:Customer {customer_id: row.customer_id})
                MATCH (o:Offer {offer_id: row.offer_id})
                MERGE (cust)-[r:SUGGESTED_OFFER]->(o)
                SET r.rank = row.rank,
                    r.match_score = row.match_score,
                    r.confidence_score = row.confidence_score,
                    r.confidence_level = row.confidence_level,
                    r.reason = row.reason,
                    r.channel = row.channel,
                    r.priority = row.priority
                """,
                rows=chunk,
            )

    return {
        "pincodes": len(pin_rows),
        "customers": len(customer_rows),
        "service_uses": len(uses_rows),
        "risk_factor_edges": len(risk_factor_rows),
        "suggested_offer_edges": len(offer_edge_rows),
        "metrics": len(slim_metrics),
        "metrics_computed": len(metric_rows),
        "patterns": len(pattern_rows),
        "offers": len(offers),
    }


def attach_diagnosis(diagnosis: dict) -> None:
    zip_code = str(diagnosis["zip_code"])
    sentence = (
        f"Diagnosis for zip {zip_code} ({diagnosis.get('city')}): {diagnosis.get('problem')} "
        f"Confidence {diagnosis.get('confidence')}. Offer {diagnosis.get('offer_id')}."
    )
    with driver().session() as session:
        _ensure_indexes(session)
        session.run(
            """
            MATCH (p:Pincode {zip: $zip})
            OPTIONAL MATCH (p)-[r:HAS_DIAGNOSIS]->(old:Diagnosis)
            DELETE r, old
            CREATE (d:Diagnosis {
                zip: $zip,
                problem: $problem,
                confidence: $confidence,
                evidence: $evidence,
                offer_id: $offer_id,
                sentence: $sentence,
                embedding: $embedding
            })
            CREATE (p)-[:HAS_DIAGNOSIS]->(d)
            WITH d
            OPTIONAL MATCH (o:Offer {offer_id: $offer_id})
            FOREACH (_ IN CASE WHEN o IS NULL THEN [] ELSE [1] END |
                CREATE (d)-[:IMPROVED_BY]->(o)
            )
            """,
            zip=zip_code,
            problem=diagnosis.get("problem") or "",
            confidence=diagnosis.get("confidence") or "low",
            evidence=json.dumps(diagnosis.get("evidence") or []),
            offer_id=diagnosis.get("offer_id"),
            sentence=sentence,
            embedding=embed(sentence),
        )


def attach_diagnoses(diagnoses: dict[str, dict]) -> int:
    count = 0
    for diagnosis in diagnoses.values():
        attach_diagnosis(diagnosis)
        count += 1
    return count


def list_pincodes(limit: int = 500, include_thin: bool = False) -> list[dict]:
    with driver().session() as session:
        records = session.run(
            """
            MATCH (p:Pincode)
            WHERE $include_thin OR coalesce(p.thin_sample, false) = false
            OPTIONAL MATCH (p)-[:HAS_DIAGNOSIS]->(d:Diagnosis)
            OPTIONAL MATCH (d)-[:IMPROVED_BY]->(o:Offer)
            RETURN p.zip AS zip_code, p.city AS city, p.state AS state, p.n AS customers,
                   coalesce(p.risk_rate, p.churn_rate) AS risk_rate,
                   coalesce(p.risk_baseline, p.churn_baseline) AS risk_baseline,
                   p.risk_score_mean AS risk_score_mean,
                   coalesce(p.risk_rate, p.churn_rate) AS churn_rate,
                   coalesce(p.risk_baseline, p.churn_baseline) AS churn_baseline,
                   p.gap_score AS gap_score, p.thin_sample AS thin_sample,
                   d.problem AS problem, d.confidence AS confidence,
                   o.offer_id AS offer_id, o.name AS offer_name
            ORDER BY p.gap_score DESC
            LIMIT $limit
            """,
            limit=limit,
            include_thin=include_thin,
        )
        return [record.data() for record in records]


def suggest_offers_from_customer_problems(customer_id: str) -> list[dict]:
    """Best-fit offers for one customer via Neo4j problem intelligence.

    Path: ``(:Customer)-[:HAS_RISK_FACTOR]->(:RiskFactor)-[:ADDRESSED_BY]->(:Offer)``
    plus any existing ``SUGGESTED_OFFER`` edges.
    """
    cid = str(customer_id or "").strip()
    if not cid:
        return []
    with driver().session() as session:
        records = session.run(
            """
            MATCH (cust:Customer {customer_id: $cid})
            OPTIONAL MATCH (cust)-[hr:HAS_RISK_FACTOR]->(rf:RiskFactor)-[:ADDRESSED_BY]->(o:Offer)
            WITH cust,
                 collect(DISTINCT CASE WHEN o IS NULL THEN NULL ELSE {
                    offer_id: o.offer_id,
                    offer_name: o.name,
                    description: o.description,
                    channel: o.channel,
                    priority: o.priority,
                    matched_patterns: [rf.code],
                    graph_score: coalesce(hr.weight, 0.5) * 10.0,
                    reason: coalesce(hr.detail, rf.label, rf.code),
                    suggested_by: 'graph'
                 } END) AS via_problems
            OPTIONAL MATCH (cust)-[r:SUGGESTED_OFFER]->(so:Offer)
            WITH via_problems,
                 collect(DISTINCT CASE WHEN so IS NULL THEN NULL ELSE {
                    offer_id: so.offer_id,
                    offer_name: so.name,
                    description: so.description,
                    channel: coalesce(r.channel, so.channel),
                    priority: coalesce(r.priority, so.priority),
                    matched_patterns: [],
                    graph_score: coalesce(r.match_score, 1),
                    reason: coalesce(r.reason, ''),
                    suggested_by: 'graph'
                 } END) AS via_edges
            RETURN [x IN via_problems WHERE x IS NOT NULL] +
                   [x IN via_edges WHERE x IS NOT NULL] AS offers
            """,
            cid=cid,
        ).single()
    if not records:
        return []
    raw = records["offers"] or []
    # Collapse duplicates keeping the strongest graph score.
    best: dict[str, dict] = {}
    for item in raw:
        offer_id = item.get("offer_id")
        if not offer_id:
            continue
        prev = best.get(offer_id)
        if prev is None or float(item.get("graph_score") or 0) > float(prev.get("graph_score") or 0):
            best[offer_id] = {
                **item,
                "suggested_resolution": item.get("reason") or "",
                "match_score": int(round(float(item.get("graph_score") or 0))),
            }
    return sorted(
        best.values(),
        key=lambda row: (
            float(row.get("graph_score") or 0),
            -int(row.get("priority") or 99),
        ),
        reverse=True,
    )


def sync_customer_suggested_offers(customer_id: str, offers: list[dict]) -> None:
    """Replace SUGGESTED_OFFER edges for one customer from ranked offer list."""
    cid = str(customer_id or "").strip()
    if not cid:
        return
    rows = []
    for offer in offers:
        offer_id = offer.get("offer_id")
        if not offer_id:
            continue
        rows.append({
            "customer_id": cid,
            "offer_id": offer_id,
            "rank": int(offer.get("rank") or 0),
            "match_score": int(offer.get("match_score") or 0),
            "confidence_score": offer.get("confidence_score"),
            "confidence_level": offer.get("confidence_level") or "",
            "reason": offer.get("suggested_resolution") or "",
            "channel": offer.get("channel") or "",
            "priority": int(offer.get("priority") or 99),
        })
    with driver().session() as session:
        session.run(
            """
            MATCH (cust:Customer {customer_id: $cid})-[r:SUGGESTED_OFFER]->(:Offer)
            DELETE r
            """,
            cid=cid,
        )
        if rows:
            session.run(
                """
                UNWIND $rows AS row
                MATCH (cust:Customer {customer_id: row.customer_id})
                MATCH (o:Offer {offer_id: row.offer_id})
                MERGE (cust)-[r:SUGGESTED_OFFER]->(o)
                SET r.rank = row.rank,
                    r.match_score = row.match_score,
                    r.confidence_score = row.confidence_score,
                    r.confidence_level = row.confidence_level,
                    r.reason = row.reason,
                    r.channel = row.channel,
                    r.priority = row.priority
                """,
                rows=rows,
            )


def get_pincode(zip_code: str) -> dict | None:
    with driver().session() as session:
        record = session.run(
            """
            MATCH (p:Pincode {zip: $zip})
            OPTIONAL MATCH (p)<-[:HAS_ZIP]-(c:City)<-[:HAS_CITY]-(st:State)
            OPTIONAL MATCH (p)-[:HAS_METRIC]->(m:MetricPoint)
            OPTIONAL MATCH (p)-[:HAS_PATTERN]->(s:PatternSignal)
            OPTIONAL MATCH (p)-[:HAS_DIAGNOSIS]->(d:Diagnosis)
            OPTIONAL MATCH (d)-[:IMPROVED_BY]->(o:Offer)
            RETURN p, st.name AS state_name, c.name AS city_name,
                   collect(DISTINCT m) AS metrics, collect(DISTINCT s) AS patterns,
                   d AS diagnosis, o AS offer
            """,
            zip=str(zip_code),
        ).single()
        if not record:
            return None
        pin = dict(record["p"])
        metrics = [dict(node) for node in record["metrics"] if node is not None]
        patterns = []
        for node in record["patterns"]:
            if node is None:
                continue
            data = dict(node)
            if data.get("metrics_json"):
                try:
                    data["metrics"] = json.loads(data["metrics_json"])
                except json.JSONDecodeError:
                    data["metrics"] = []
            patterns.append(data)
        diagnosis = dict(record["diagnosis"]) if record["diagnosis"] else None
        offer = dict(record["offer"]) if record["offer"] else None

        customer_records = session.run(
            """
            MATCH (p:Pincode {zip: $zip})-[:HAS_CUSTOMER]->(cust:Customer)
            OPTIONAL MATCH (cust)-[r:SUGGESTED_OFFER]->(so:Offer)
            OPTIONAL MATCH (cust)-[u:USES]->(svc:Service)
            OPTIONAL MATCH (cust)-[hr:HAS_RISK_FACTOR]->(rf:RiskFactor)
            OPTIONAL MATCH (cust)-[:ON_CONTRACT]->(ct:ContractType)
            WITH cust, r, so, u, svc, hr, rf, ct
            ORDER BY coalesce(r.rank, 99)
            WITH cust, ct,
                 collect(DISTINCT CASE WHEN so IS NULL THEN NULL ELSE {
                    offer_id: so.offer_id,
                    offer_name: so.name,
                    channel: coalesce(r.channel, so.channel),
                    priority: coalesce(r.priority, so.priority),
                    match_score: r.match_score,
                    rank: r.rank,
                    suggested_resolution: r.reason,
                    suggested_by: 'rules'
                 } END) AS offers,
                 collect(DISTINCT CASE WHEN svc IS NULL THEN NULL ELSE {
                    name: svc.name,
                    detail: u.detail,
                    avg_monthly_gb: u.avg_monthly_gb
                 } END) AS active_services,
                 collect(DISTINCT CASE WHEN rf IS NULL THEN NULL ELSE {
                    code: rf.code,
                    label: rf.label,
                    detail: hr.detail,
                    weight: hr.weight
                 } END) AS risk_factors
            RETURN cust, ct.name AS contract_name,
                   [x IN offers WHERE x IS NOT NULL] AS suggested_offers,
                   [x IN active_services WHERE x IS NOT NULL] AS active_services,
                   [x IN risk_factors WHERE x IS NOT NULL] AS risk_factors
            ORDER BY coalesce(cust.high_risk, false) DESC, coalesce(cust.clv_eur, 0) DESC
            """,
            zip=str(zip_code),
        )
        customers_detail = []
        from app.analysis.customer_campaigns import (
            build_suggested_campaign,
            build_suggested_offers,
        )

        for crow in customer_records:
            cust = dict(crow["cust"])
            cust.pop("embedding", None)
            suggested = crow["suggested_offers"] or []
            risk_factors = crow["risk_factors"] or []
            services_payload = None
            if cust.get("services_json"):
                try:
                    services_payload = json.loads(cust["services_json"])
                except json.JSONDecodeError:
                    services_payload = None
            if services_payload is None:
                services_payload = {
                    "active": crow["active_services"] or [],
                    "contract": crow.get("contract_name"),
                }
            high_risk = bool(cust.get("high_risk"))
            # Rebuild from Neo4j problem→offer intelligence when edges are thin/stale.
            if high_risk:
                graph_offers = suggest_offers_from_customer_problems(str(cust.get("customer_id") or ""))
                rebuilt = build_suggested_offers(
                    high_risk=True,
                    risk_factors=risk_factors,
                    services=services_payload,
                    graph_offers=graph_offers,
                )
                if rebuilt:
                    suggested = rebuilt
            suggested_campaign = build_suggested_campaign(suggested)
            primary = (
                (suggested[0].get("offer_id") if suggested else None)
                or cust.get("primary_offer_id")
            )
            customers_detail.append({
                "customer_id": cust.get("customer_id"),
                "customer_ref": cust.get("customer_ref"),
                "contract_type": cust.get("contract_type"),
                "churn_score": cust.get("churn_score"),
                "churn_probability": cust.get("churn_probability"),
                "satisfaction_score": cust.get("satisfaction_score"),
                "clv_eur": cust.get("clv_eur"),
                "high_risk": high_risk,
                "campaign_eligible": high_risk,
                "campaign_status": cust.get("campaign_status"),
                "primary_offer_id": primary,
                "services": services_payload,
                "risk_factors": risk_factors,
                "suggested_offers": suggested,
                "suggested_campaign": suggested_campaign,
            })

        # strip embeddings from API payload
        for item in metrics + patterns + ([diagnosis] if diagnosis else []) + ([offer] if offer else []):
            item.pop("embedding", None)
        pin.pop("embedding", None)
        return {
            "zip_code": pin.get("zip"),
            "city": record.get("city_name") or pin.get("city"),
            "state": record.get("state_name") or pin.get("state"),
            "customers": pin.get("n"),
            "population": pin.get("population"),
            "risk_rate": pin.get("risk_rate", pin.get("churn_rate")),
            "risk_baseline": pin.get("risk_baseline", pin.get("churn_baseline")),
            "risk_score_mean": pin.get("risk_score_mean"),
            "churn_rate": pin.get("risk_rate", pin.get("churn_rate")),
            "churn_baseline": pin.get("risk_baseline", pin.get("churn_baseline")),
            "thin_sample": pin.get("thin_sample"),
            "gap_score": pin.get("gap_score"),
            "sentence": pin.get("sentence"),
            "metrics": sorted(metrics, key=lambda item: abs(item.get("gap_score") or 0), reverse=True)[:20],
            "patterns": patterns,
            "diagnosis": diagnosis,
            "offer": offer,
            "customers_detail": customers_detail,
        }


def vector_search(query: str, limit: int = 5) -> list[dict]:
    """Hybrid-ish search: query each vector index and expand to pincode."""
    vector = embed(query)
    results: list[dict] = []
    with driver().session() as session:
        for index_name, label in [
            (METRIC_INDEX, "MetricPoint"),
            (PATTERN_INDEX, "PatternSignal"),
            (DIAGNOSIS_INDEX, "Diagnosis"),
            (OFFER_INDEX, "Offer"),
            (PINCODE_INDEX, "Pincode"),
            (CUSTOMER_INDEX, "Customer"),
        ]:
            try:
                records = session.run(
                    f"""
                    CALL db.index.vector.queryNodes('{index_name}', $limit, $vector)
                    YIELD node, score
                    OPTIONAL MATCH (p:Pincode)-[:HAS_METRIC|HAS_PATTERN|HAS_DIAGNOSIS|HAS_CUSTOMER]->(node)
                    OPTIONAL MATCH (p2:Pincode) WHERE node:Pincode AND p2 = node
                    OPTIONAL MATCH (d:Diagnosis)-[:IMPROVED_BY]->(node)
                    OPTIONAL MATCH (pd:Pincode)-[:HAS_DIAGNOSIS]->(d)
                    OPTIONAL MATCH (pc:Pincode)-[:HAS_CUSTOMER]->(node)
                    OPTIONAL MATCH (pc)<-[:HAS_ZIP]-(cityNode:City)<-[:HAS_CITY]-(stateNode:State)
                    WITH node, score,
                         coalesce(p.zip, p2.zip, pd.zip, pc.zip, node.zip) AS zip,
                         coalesce(p.city, p2.city, pd.city, pc.city, cityNode.name, node.city) AS city,
                         coalesce(stateNode.name, pc.state, node.state) AS state,
                         node.sentence AS sentence,
                         labels(node) AS labels
                    RETURN zip, city, state, sentence, score, labels
                    LIMIT $limit
                    """,
                    limit=limit,
                    vector=vector,
                )
                for record in records:
                    results.append(record.data())
            except Exception:
                continue
    results.sort(key=lambda item: item.get("score") or 0, reverse=True)
    # de-dupe by sentence
    seen = set()
    unique = []
    for item in results:
        key = (item.get("zip"), item.get("sentence"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:limit]


def graphrag_search(question: str, top_k: int = 5) -> list[dict]:
    """Prefer neo4j-graphrag Hybrid/Vector retriever; fall back to vector_search."""
    try:
        from neo4j_graphrag.embeddings import Embedder
        from neo4j_graphrag.retrievers import VectorCypherRetriever

        class HashEmbedder(Embedder):
            def embed_query(self, text: str) -> list[float]:
                return embed(text)

        retrieval_query = """
        WITH node, score
        OPTIONAL MATCH (p:Pincode)-[:HAS_METRIC|HAS_PATTERN|HAS_DIAGNOSIS|HAS_CUSTOMER]->(node)
        OPTIONAL MATCH (p2:Pincode) WHERE node:Pincode AND p2 = node
        OPTIONAL MATCH (d:Diagnosis)-[:IMPROVED_BY]->(node)
        OPTIONAL MATCH (pd:Pincode)-[:HAS_DIAGNOSIS]->(d)
        OPTIONAL MATCH (pc:Pincode)-[:HAS_CUSTOMER]->(node)
        OPTIONAL MATCH (pin:Pincode)
          WHERE pin.zip = coalesce(p.zip, p2.zip, pd.zip, pc.zip, node.zip)
        OPTIONAL MATCH (pin)<-[:HAS_ZIP]-(cityNode:City)<-[:HAS_CITY]-(stateNode:State)
        OPTIONAL MATCH (pin)-[:HAS_DIAGNOSIS]->(diag:Diagnosis)
        OPTIONAL MATCH (diag)-[:IMPROVED_BY]->(offer:Offer)
        OPTIONAL MATCH (node)-[:SUGGESTED_OFFER]->(custOffer:Offer)
        RETURN coalesce(node.sentence, pin.sentence) AS text,
               coalesce(pin.zip, node.zip) AS zip_code,
               coalesce(pin.city, cityNode.name, node.city) AS city,
               coalesce(stateNode.name, pin.state, node.state) AS state,
               diag.problem AS problem,
               coalesce(offer.offer_id, custOffer.offer_id) AS offer_id,
               coalesce(offer.name, custOffer.name) AS offer_name,
               score
        """
        retriever = VectorCypherRetriever(
            driver=driver(),
            index_name=METRIC_INDEX,
            embedder=HashEmbedder(),
            retrieval_query=retrieval_query,
        )
        result = retriever.search(query_text=question, top_k=top_k)
        items = []
        for item in result.items:
            content = item.content
            if isinstance(content, str):
                items.append({"sentence": content, "score": item.metadata.get("score") if item.metadata else None})
            elif isinstance(content, dict):
                items.append(content)
            else:
                items.append({"sentence": str(content)})
        if items:
            return items
    except Exception:
        pass
    return vector_search(question, limit=top_k)
