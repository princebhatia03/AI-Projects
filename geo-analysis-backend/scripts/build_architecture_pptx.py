"""Build the Geo Analysis architecture PowerPoint from the UI and backend."""

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

NAVY = RGBColor(0x0C, 0x23, 0x40)
NAVY_2 = RGBColor(0x14, 0x33, 0x58)
TEAL = RGBColor(0x0E, 0x7A, 0x74)
TEAL_DEEP = RGBColor(0x0A, 0x5C, 0x58)
GOLD = RGBColor(0xC4, 0x8A, 0x1A)
INK = RGBColor(0x1C, 0x28, 0x36)
MUTED = RGBColor(0x5C, 0x6B, 0x7A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
ICE = RGBColor(0xF4, 0xF7, 0xFB)
CARD = RGBColor(0xFF, 0xFF, 0xFF)
LINE = RGBColor(0xD5, 0xDE, 0xE8)
SOFT_TEAL = RGBColor(0xE6, 0xF4, 0xF3)
SOFT_NAVY = RGBColor(0xE8, 0xEE, 0xF6)
SOFT_GOLD = RGBColor(0xFB, 0xF4, 0xE4)
SOFT_CORAL = RGBColor(0xFB, 0xEE, 0xEB)
CORAL = RGBColor(0xB8, 0x4A, 0x3A)

W = 13.333
H = 7.5
FONT = "Calibri"


def _set_fill(shape, color):
    shape.fill.solid()
    shape.fill.fore_color.rgb = color


def _no_line(shape):
    shape.line.fill.background()


def _line(shape, color, pt=1.0):
    shape.line.color.rgb = color
    shape.line.width = Pt(pt)


def _font(run, size, color, bold=False):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.bold = bold


def rect(slide, x, y, w, h, fill, line=None, radius=0.08):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h)
    )
    try:
        shape.adjustments[0] = radius
    except Exception:
        pass
    _set_fill(shape, fill)
    if line is None:
        _no_line(shape)
    else:
        _line(shape, line, 1.0)
    shape.shadow.inherit = False
    return shape


def box(slide, x, y, w, h, fill):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    _set_fill(shape, fill)
    _no_line(shape)
    shape.shadow.inherit = False
    return shape


def tb(slide, x, y, w, h, text, size=14, color=INK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = shape.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    tf.margin_left = Emu(0)
    tf.margin_right = Emu(0)
    tf.margin_top = Emu(0)
    tf.margin_bottom = Emu(0)
    try:
        tf._txBody.bodyPr.set("anchor", {MSO_ANCHOR.TOP: "t", MSO_ANCHOR.MIDDLE: "ctr", MSO_ANCHOR.BOTTOM: "b"}[anchor])
    except Exception:
        pass
    parts = text.split("\n")
    for i, part in enumerate(parts):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_before = Pt(0)
        p.space_after = Pt(0)
        run = p.add_run()
        run.text = part
        _font(run, size, color, bold)
    return shape


def lines(slide, x, y, w, h, items, size=13, color=INK, bullet=True, gap=4, bold_lead=False):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = shape.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    tf.margin_left = Emu(0)
    tf.margin_right = Emu(0)
    tf.margin_top = Emu(0)
    tf.margin_bottom = Emu(0)
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.space_before = Pt(0)
        p.space_after = Pt(gap)
        run = p.add_run()
        prefix = "•  " if bullet else ""
        run.text = prefix + item
        _font(run, size, color, bold_lead and i == 0)
    return shape


def footer(slide, n, total):
    box(slide, 0, 7.22, W, 0.28, ICE)
    tb(slide, 0.45, 7.24, 8, 0.24, "Geo Analysis  ·  UI and backend architecture", 10, MUTED)
    tb(slide, 11.2, 7.24, 1.7, 0.24, f"{n}  /  {total}", 10, MUTED, align=PP_ALIGN.RIGHT)


def header(slide, kicker, title, subtitle=None):
    box(slide, 0, 0, W, 0.08, TEAL)
    tb(slide, 0.48, 0.22, 12, 0.26, kicker.upper(), 11, TEAL, bold=True)
    tb(slide, 0.46, 0.46, 12.2, 0.46, title, 28, NAVY, bold=True)
    if subtitle:
        tb(slide, 0.48, 0.98, 12.2, 0.32, subtitle, 14, MUTED)


def new(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def build():
    prs = Presentation()
    prs.slide_width = Inches(W)
    prs.slide_height = Inches(H)
    prs.core_properties.title = "Geo Analysis — Architecture"
    prs.core_properties.subject = "Pincode churn risk, diagnosis, and campaigns"
    total = 10

    # ----- 1. Title -----
    s = new(prs)
    box(s, 0, 0, W, H, NAVY)
    box(s, 0, 0, 0.16, H, GOLD)
    tb(s, 0.7, 1.55, 10, 0.32, "ARCHITECTURE BRIEFING", 14, GOLD, bold=True)
    tb(s, 0.68, 2.0, 11.5, 1.1, "Geo Analysis", 60, WHITE, bold=True)
    tb(
        s,
        0.72,
        3.2,
        10.5,
        0.9,
        "How the pincode workspace predicts churn risk,\ndiagnoses an area, and turns that into a retention campaign.",
        20,
        RGBColor(0xD5, 0xE2, 0xEE),
    )
    widths = [1.7, 1.35, 2.15, 1.75, 1.85]
    labels = ["Next.js UI", "FastAPI", "Pandas pipeline", "Neo4j graph", "Google ADK"]
    x = 0.72
    for label, width in zip(labels, widths):
        rect(s, x, 4.7, width, 0.46, RGBColor(0x18, 0x3E, 0x66), radius=0.5)
        tb(s, x, 4.78, width, 0.32, label, 13, WHITE, bold=True, align=PP_ALIGN.CENTER)
        x += width + 0.16
    tb(s, 0.72, 6.35, 8, 0.3, "geo-analysis-ui   ·   geo-analysis-backend", 14, RGBColor(0x9A, 0xB4, 0xC8))
    tb(s, 0.72, 6.7, 8, 0.28, "October 2026", 13, RGBColor(0x7E, 0x96, 0xAA))
    notes(
        s,
        "Open with the product, not the stack. The system tells a sales analyst which postal areas "
        "are at risk, why, and which retention offer to run. The rest of the deck shows how UI, API, "
        "pipeline, agents, and Neo4j fit together.",
    )

    # ----- 2. What it does -----
    s = new(prs)
    box(s, 0, 0, W, H, WHITE)
    header(s, "Product", "Three jobs, one workspace", "Built for still-active subscribers. Risk is predicted, not a count of people who already left.")
    footer(s, 2, total)
    cards = [
        (SOFT_CORAL, CORAL, "01", "See risk by place", [
            "Honeycomb groups every zip into a city.",
            "Hex color is the city’s average predicted high-risk share.",
            "State filter, search, and a live / empty / offline status.",
        ]),
        (SOFT_TEAL, TEAL, "02", "Read one pincode", [
            "Business impact in EUR: at-risk CLV and upsell.",
            "Customer cards with contract, score, and risk factors.",
            "Each zip is compared with the rest of its state.",
        ]),
        (SOFT_GOLD, GOLD, "03", "Act on a customer", [
            "An agent writes why that person may leave.",
            "Offers are matched from the menu, via the graph.",
            "Triggering a campaign is stored in SQLite.",
        ]),
    ]
    for i, (fill, accent, num, title, bullets) in enumerate(cards):
        x = 0.45 + i * 4.25
        rect(s, x, 1.7, 4.05, 3.85, fill, radius=0.06)
        box(s, x, 1.7, 0.1, 3.85, accent)
        tb(s, x + 0.32, 1.9, 3.4, 0.36, num, 14, accent, bold=True)
        tb(s, x + 0.32, 2.28, 3.5, 0.5, title, 22, NAVY, bold=True)
        lines(s, x + 0.32, 3.05, 3.5, 2.2, bullets, size=15, color=INK, gap=10)
    rect(s, 0.45, 5.75, 12.4, 1.25, ICE, radius=0.05)
    tb(s, 0.7, 5.92, 12, 0.3, "Accuracy rule", 14, TEAL, bold=True)
    tb(
        s,
        0.7,
        6.26,
        11.9,
        0.55,
        "Rates, gaps, and euro figures come from pandas and Neo4j. The language model explains a customer and chooses an offer id from the catalog. It does not invent aggregates.",
        15,
        INK,
    )
    notes(
        s,
        "Source of truth for numbers is the deterministic analysis, not the LLM. "
        "HIGH_RISK_SCORE defaults to 65. CLV uses ARPU, gross margin, and a contract-based monthly churn rate, then expected loss is CLV times probability.",
    )

    # ----- 3. System architecture -----
    s = new(prs)
    box(s, 0, 0, W, H, WHITE)
    header(s, "System", "How the pieces talk", "The browser never reads Neo4j. Every screen goes through the FastAPI on port 8000.")
    footer(s, 3, total)

    def node(x, y, w, h, fill, title, body, title_color=WHITE, body_color=RGBColor(0xE4, 0xEE, 0xF5)):
        rect(s, x, y, w, h, fill, radius=0.08)
        tb(s, x + 0.16, y + 0.12, w - 0.3, 0.32, title, 14, title_color, bold=True)
        tb(s, x + 0.16, y + 0.44, w - 0.3, h - 0.55, body, 12, body_color)

    node(0.4, 1.6, 2.15, 1.55, NAVY, "Analyst", "Browser\nlocalhost:3000")
    # arrow
    arr = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(2.65), Inches(2.15), Inches(0.38), Inches(0.28))
    _set_fill(arr, TEAL)
    _no_line(arr)
    node(3.15, 1.55, 3.15, 1.7, TEAL, "Next.js UI", "AppShell\nRisk Honeycomb\nArea Studio")
    arr = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(6.42), Inches(2.15), Inches(0.38), Inches(0.28))
    _set_fill(arr, TEAL)
    _no_line(arr)
    tb(s, 6.28, 1.85, 0.7, 0.28, "REST", 10, TEAL, bold=True, align=PP_ALIGN.CENTER)
    node(6.9, 1.45, 3.35, 1.9, NAVY_2, "FastAPI", "Routes  ·  pipeline state\nAnalysis  ·  ADK agents\nlocalhost:8000")
    arr = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(10.35), Inches(2.15), Inches(0.32), Inches(0.28))
    _set_fill(arr, GOLD)
    _no_line(arr)
    tb(s, 10.15, 1.85, 0.7, 0.28, "Bolt", 10, GOLD, bold=True, align=PP_ALIGN.CENTER)
    node(10.75, 1.55, 2.15, 1.7, RGBColor(0x1F, 0x4B, 0x3A), "Neo4j 5.26", "Graph + vectors\n7687  ·  7474")

    # lower band
    stores = [
        (0.4, SOFT_NAVY, NAVY, "DataSet CSVs", "Demographics, services,\nstatus, location, population"),
        (3.55, SOFT_TEAL, TEAL_DEEP, "JSON artifacts", "Profiles, diagnoses,\noffers, catalog, meta"),
        (6.7, SOFT_GOLD, GOLD, "SQLite", "campaign_history\nin artifacts/campaigns.db"),
        (9.85, SOFT_CORAL, CORAL, "LLM", "Azure OpenAI or\nLM Studio via LiteLLM"),
    ]
    for x, fill, accent, title, body in stores:
        rect(s, x, 3.6, 3.0, 1.35, fill, radius=0.06)
        box(s, x, 3.6, 0.08, 1.35, accent)
        tb(s, x + 0.22, 3.72, 2.65, 0.3, title, 14, accent, bold=True)
        tb(s, x + 0.22, 4.08, 2.65, 0.7, body, 12, INK)

    rect(s, 0.4, 5.15, 12.5, 1.85, ICE, radius=0.05)
    tb(s, 0.62, 5.3, 12, 0.28, "Startup", 13, TEAL, bold=True)
    lines(
        s,
        0.62,
        5.62,
        12.0,
        1.25,
        [
            "Lifespan opens SQLite, then loads artifacts into memory if they already exist.",
            "If artifacts are missing, status stays empty until POST /pipeline/run.",
            "CORS allows only the UI origins on port 3000. Shutdown closes the Neo4j driver.",
        ],
        size=14,
        gap=4,
    )
    notes(
        s,
        "docker-compose runs neo4j:5.26 with auth read from NEO4J_PASSWORD, ports 7474 and 7687. "
        "UI base URL is NEXT_PUBLIC_API_URL, default http://localhost:8000. "
        "Pipeline run from the honeycomb is POST /pipeline/run with mode auto, and the route currently executes the deterministic tool sequence.",
    )

    # ----- 4. UI -----
    s = new(prs)
    box(s, 0, 0, W, H, WHITE)
    header(s, "Frontend", "Two screens, one shell", "geo-analysis-ui  ·  Next.js 15, React 19, Tailwind 4. The page renders AppShell and nothing else.")
    footer(s, 4, total)

    rect(s, 0.4, 1.55, 6.15, 5.4, ICE, radius=0.06)
    tb(s, 0.62, 1.72, 5.7, 0.32, "Risk Honeycomb", 18, NAVY, bold=True)
    tb(s, 0.62, 2.08, 5.7, 0.4, "Home screen. Cities as flat-top hexes via react-hexgrid.", 13, MUTED)
    lines(
        s,
        0.62,
        2.55,
        5.7,
        4.1,
        [
            "GET /pipeline/status — Live, Empty, or Offline.",
            "GET /pincodes?include_thin=true — one row per zip.",
            "Zips roll up to a city: customers, high-risk count, average risk, euro impact.",
            "Color bands at 40% and 55% average risk.",
            "State summary, city search, pin a city, then open it.",
            "Run pipeline calls POST /pipeline/run and reloads the map.",
        ],
        size=14,
        gap=8,
    )

    rect(s, 6.75, 1.55, 6.15, 5.4, SOFT_TEAL, radius=0.06)
    tb(s, 6.97, 1.72, 5.7, 0.32, "Area Studio", 18, NAVY, bold=True)
    tb(s, 6.97, 2.08, 5.7, 0.4, "Opened when a hex is clicked. Back returns to the map.", 13, MUTED)
    lines(
        s,
        6.97,
        2.55,
        5.7,
        4.1,
        [
            "Filters: state, city, zip.",
            "GET /pincode/{zip} — impact, customers, drivers.",
            "GET /offers and GET /campaigns for the menus and history.",
            "POST …/suggest-actions refreshes upsells and offers.",
            "POST …/customers/{id}/explain runs the risk agent.",
            "POST …/campaign writes the trigger for selected customers.",
        ],
        size=14,
        gap=8,
    )
    notes(
        s,
        "Components: AppShell, RiskHoneycomb, AreaStudio, ZoomPanViewport, SearchableSelect, InfoTip, plus small ui primitives. "
        "Types live in lib/types.ts, including Place, CustomerCard, Offer, and the API_URL constant.",
    )

    # ----- 5. Backend layers -----
    s = new(prs)
    box(s, 0, 0, W, H, WHITE)
    header(s, "Backend", "Layers inside FastAPI", "Python 3.13. Each layer has one job. Agents call tools; they do not recompute rates.")
    footer(s, 5, total)

    layers = [
        (NAVY, WHITE, RGBColor(0xD5, 0xE2, 0xEE), "API", "app/api/routes.py", "Status, pincodes, detail, offers, campaigns, pipeline run, suggest-actions, explain, agent ask."),
        (TEAL, WHITE, RGBColor(0xE5, 0xF6, 0xF4), "Orchestration", "app/pipeline", "churn_pipeline runs seven tools in order. state.py holds profiles in memory and writes JSON."),
        (RGBColor(0x1F, 0x4B, 0x3A), WHITE, RGBColor(0xE3, 0xF2, 0xEA), "Analysis", "app/analysis", "Load and join CSVs, pattern catalog, pincode aggregate, diagnosis, CLV, offers, campaigns."),
        (NAVY_2, WHITE, RGBColor(0xD5, 0xE2, 0xEE), "Agents", "app/agents", "Google ADK app: coordinator, sequential pipeline, query agent, customer risk agent. Tools in churn_tools.py."),
        (RGBColor(0x3D, 0x4A, 0x5C), WHITE, RGBColor(0xE8, 0xEE, 0xF4), "Storage", "app/storage", "Neo4j writer and GraphRAG, SQLite campaign history, 128-d embeddings."),
    ]
    for i, (fill, tc, bc, name, path, desc) in enumerate(layers):
        y = 1.52 + i * 1.08
        rect(s, 0.45, y, 12.4, 0.98, fill, radius=0.05)
        tb(s, 0.7, y + 0.14, 2.3, 0.32, name, 18, tc, bold=True)
        tb(s, 0.7, y + 0.5, 2.3, 0.3, path, 12, bc)
        tb(s, 3.2, y + 0.28, 9.3, 0.5, desc, 15, WHITE)
    notes(
        s,
        "Analysis modules: loader, local_dataset, pattern_catalog, pincode_aggregate, diagnosis, "
        "business_impact, behaviour_actions, customer_risk, customer_services, customer_campaigns, "
        "domain_metrics, offers. Config in app/config.py reads .env.",
    )

    # ----- 6. Pipeline -----
    s = new(prs)
    box(s, 0, 0, W, H, WHITE)
    header(s, "Pipeline", "Seven steps, always in this order", "POST /pipeline/run calls run_pipeline_deterministic. A step that returns ok: false stops the run.")
    footer(s, 6, total)

    steps = [
        ("1", "Load dataset", "Join the telco CSVs on customer id. Grain becomes zip, city, and state."),
        ("2", "Resolve catalog", "Lock the pattern catalog: what to measure, and which fields are drivers."),
        ("3", "Aggregate", "Pandas rolls each zip against the rest of its state. Thin samples are flagged."),
        ("4", "Load offers", "Read the offer menu. Later steps may only assign ids from this list."),
        ("5", "Write graph", "Replace the Neo4j graph: places, customers, services, factors, offers."),
        ("6", "Diagnose", "Top pincodes get a problem statement, evidence, and one preventive offer."),
        ("7", "Persist", "Write JSON artifacts and refresh the in-memory status the UI polls."),
    ]
    for i, (num, title, desc) in enumerate(steps):
        col = i if i < 4 else i - 4
        row = 0 if i < 4 else 1
        x = 0.4 + col * 3.22
        y = 1.58 + row * 2.15
        rect(s, x, y, 3.05, 1.98, ICE, radius=0.06)
        circ = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + 0.16), Inches(y + 0.16), Inches(0.38), Inches(0.38))
        _set_fill(circ, TEAL if i < 6 else GOLD)
        _no_line(circ)
        tb(s, x + 0.16, y + 0.2, 0.38, 0.32, num, 14, WHITE, bold=True, align=PP_ALIGN.CENTER)
        tb(s, x + 0.62, y + 0.18, 2.25, 0.34, title, 16, NAVY, bold=True)
        tb(s, x + 0.18, y + 0.7, 2.7, 1.1, desc, 13, INK)

    rect(s, 0.4, 5.95, 12.5, 1.05, SOFT_GOLD, radius=0.05)
    tb(
        s,
        0.62,
        6.15,
        12.1,
        0.7,
        "An ADK SequentialAgent can run the same tools (ingest → pattern → aggregate → diagnosis). If the model is not configured, or the agent run fails, the API falls back to this fixed sequence.",
        14,
        INK,
    )
    notes(
        s,
        "Tool order in churn_pipeline._PIPELINE_STEPS: load_from_dataset, resolve_catalog, "
        "run_pincode_aggregation, load_offers, write_pincode_graph, diagnose_top_pincodes, persist_pipeline_state. "
        "MIN_N defaults to 30. SHARE_DELTA 0.05. MEAN_RELATIVE 0.15. DIAGNOSIS_TOP_N 40.",
    )

    # ----- 7. Agents -----
    s = new(prs)
    box(s, 0, 0, W, H, WHITE)
    header(s, "Agents", "One coordinator, three specialists", "Google ADK App named geo_churn. Model is LiteLLM: azure/<deployment> or openai/<LM Studio model>.")
    footer(s, 7, total)

    rect(s, 4.35, 1.55, 4.6, 0.85, NAVY, radius=0.08)
    tb(s, 4.5, 1.65, 4.3, 0.32, "coordinator", 16, WHITE, bold=True, align=PP_ALIGN.CENTER)
    tb(s, 4.5, 1.98, 4.3, 0.3, "Routes the user request", 12, RGBColor(0xD5, 0xE2, 0xEE), align=PP_ALIGN.CENTER)

    # three arrows down - simple bars
    for x in (2.15, 6.45, 10.55):
        bar = s.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(x), Inches(2.5), Inches(0.28), Inches(0.32))
        _set_fill(bar, TEAL)
        _no_line(bar)

    agents = [
        (0.4, TEAL, "churn_pipeline", "SequentialAgent", [
            "ingest_agent — load and preview CSVs",
            "pattern_agent — resolve the catalog",
            "aggregate_agent — rollups, offers, graph",
            "diagnosis_agent — top zips, then persist",
        ]),
        (4.55, NAVY_2, "query_agent", "POST /agent/ask", [
            "Sales questions about a place",
            "neo4j_graphrag_search",
            "Optional get_pincode_profile",
            "Answer cites only tool hits",
        ]),
        (8.7, RGBColor(0x1F, 0x4B, 0x3A), "customer_risk_agent", "Explain one customer", [
            "get_high_risk_customer_facts",
            "Write 1–2 sentences from those facts",
            "save_customer_risk_why",
            "UI: POST …/customers/{id}/explain",
        ]),
    ]
    for x, fill, title, sub, bullets in agents:
        rect(s, x, 2.95, 3.95, 2.85, fill, radius=0.06)
        tb(s, x + 0.18, 3.08, 3.6, 0.32, title, 15, WHITE, bold=True)
        tb(s, x + 0.18, 3.4, 3.6, 0.28, sub, 12, RGBColor(0xD7, 0xE8, 0xE4))
        lines(s, x + 0.18, 3.8, 3.6, 1.85, bullets, size=13, color=WHITE, gap=4)

    rect(s, 0.4, 5.98, 12.5, 1.02, ICE, radius=0.05)
    tb(
        s,
        0.6,
        6.15,
        12.1,
        0.7,
        "ReflectAndRetryToolPlugin retries a failed tool twice. Sessions are in memory. The UI does not chat with the coordinator; explain and pipeline are explicit REST calls.",
        14,
        INK,
    )
    notes(
        s,
        "build_pipeline_app in app/agents/runtime.py. query path also has a non-agent fallback in ask_graph: "
        "GraphRAG hits, then LiteLLM synthesis only when the provider is configured.",
    )

    # ----- 8. Graph -----
    s = new(prs)
    box(s, 0, 0, W, H, WHITE)
    header(s, "Data model", "What Neo4j stores", "The pipeline rebuilds the graph. Offer matching walks Customer → risk factor → offer.")
    footer(s, 8, total)

    # geography chain
    pills = [("State", 0.45), ("City", 2.35), ("Pincode", 4.25)]
    rels_top = [(1.85, "HAS_CITY"), (3.75, "HAS_ZIP")]
    for name, x in pills:
        rect(s, x, 1.55, 1.35, 0.46, NAVY, radius=0.4)
        tb(s, x, 1.64, 1.35, 0.3, name, 13, WHITE, bold=True, align=PP_ALIGN.CENTER)
    for x, label in rels_top:
        tb(s, x, 1.64, 0.9, 0.28, label, 9, TEAL, bold=True, align=PP_ALIGN.CENTER)

    # fan from pincode
    children = [
        (0.4, "Customer", "HAS_CUSTOMER"),
        (2.55, "MetricPoint", "HAS_METRIC"),
        (4.7, "PatternSignal", "HAS_PATTERN"),
        (6.85, "Diagnosis", "HAS_DIAGNOSIS"),
    ]
    for x, name, rel in children:
        tb(s, x, 2.15, 1.9, 0.24, rel, 10, TEAL, bold=True, align=PP_ALIGN.CENTER)
        rect(s, x + 0.15, 2.4, 1.6, 0.42, SOFT_NAVY, LINE, radius=0.3)
        tb(s, x + 0.15, 2.47, 1.6, 0.3, name, 12, NAVY, bold=True, align=PP_ALIGN.CENTER)

    # customer detail + offer
    rect(s, 0.4, 3.1, 8.15, 2.55, ICE, radius=0.05)
    tb(s, 0.58, 3.22, 7.8, 0.28, "From a customer", 13, TEAL, bold=True)
    edges = [
        "USES  →  Service",
        "ON_CONTRACT  →  ContractType",
        "HAS_RISK_FACTOR  →  RiskFactor  →  ADDRESSED_BY  →  Offer",
        "SUGGESTED_OFFER  →  Offer",
    ]
    lines(s, 0.58, 3.55, 7.7, 1.9, edges, size=14, gap=6)

    rect(s, 8.75, 3.1, 4.15, 2.55, SOFT_GOLD, radius=0.05)
    tb(s, 8.93, 3.22, 3.8, 0.28, "Also on the graph", 13, GOLD, bold=True)
    lines(
        s,
        8.93,
        3.58,
        3.8,
        1.9,
        [
            "Pincode IN_CITY City",
            "Pattern ADDRESSED_BY Offer",
            "Diagnosis IMPROVED_BY Offer",
            "City HAS_ZIP is the place key",
        ],
        size=13,
        gap=6,
    )

    rect(s, 0.4, 5.82, 12.5, 1.18, SOFT_TEAL, radius=0.05)
    tb(s, 0.6, 5.96, 12.1, 0.26, "GraphRAG", 13, TEAL_DEEP, bold=True)
    tb(
        s,
        0.6,
        6.28,
        12.1,
        0.55,
        "Each node carries a sentence and a 128-dimension embedding. Vector indexes use cosine similarity on Pincode, Customer, MetricPoint, PatternSignal, Diagnosis, and Offer.",
        14,
        INK,
    )
    notes(
        s,
        "write_pincode_graph clears the graph, upserts offers, then writes geography, a slim set of metric points (top gaps), "
        "patterns, customers, USES, contracts, risk factors, and suggested offers. attach_diagnosis adds Diagnosis and IMPROVED_BY. "
        "suggest_offers_from_customer_problems is the Cypher path the suggest-actions endpoint uses.",
    )

    # ----- 9. Journey -----
    s = new(prs)
    box(s, 0, 0, W, H, WHITE)
    header(s, "Runtime", "From a hex click to a campaign", "The path a user actually takes. Each step is one HTTP call.")
    footer(s, 9, total)

    journey = [
        ("1", "Open the map", "GET /pipeline/status and GET /pincodes. Hexes render from the city rollup."),
        ("2", "Open a city", "Area Studio loads offers, campaign history, and GET /pincode/{zip}."),
        ("3", "Refresh actions", "POST suggest-actions rebuilds upsells and rewrites SUGGESTED_OFFER edges."),
        ("4", "Explain", "POST …/explain. The customer risk agent reads facts and saves risk_why."),
        ("5", "Trigger", "POST …/campaign. High-risk customers and one offer id are stored in SQLite."),
        ("6", "History", "GET /campaigns reads that table back into the studio, for the zip or for all."),
    ]
    for i, (num, title, desc) in enumerate(journey):
        col = i % 3
        row = i // 3
        x = 0.4 + col * 4.25
        y = 1.58 + row * 2.55
        rect(s, x, y, 4.05, 2.35, ICE, radius=0.06)
        circ = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + 0.18), Inches(y + 0.2), Inches(0.42), Inches(0.42))
        _set_fill(circ, TEAL)
        _no_line(circ)
        tb(s, x + 0.18, y + 0.26, 0.42, 0.32, num, 16, WHITE, bold=True, align=PP_ALIGN.CENTER)
        tb(s, x + 0.72, y + 0.24, 3.1, 0.36, title, 18, NAVY, bold=True)
        tb(s, x + 0.2, y + 0.85, 3.65, 1.25, desc, 14, INK)
    notes(
        s,
        "suggest-actions uses behaviour_actions.enrich_profile_with_behaviour with use_ai_campaigns, "
        "then customer_campaigns.build_suggested_offers, preferring graph offers from the risk-factor path. "
        "trigger_campaign_for_zip records campaign_id, zip, offer, customer refs, and CLV.",
    )

    # ----- 10. Stack -----
    s = new(prs)
    box(s, 0, 0, W, H, WHITE)
    header(s, "Reference", "Stack, files, and ports", "What to start, and where each fact lives after a pipeline run.")
    footer(s, 10, total)

    # table-like rows
    rows = [
        ("UI", "Next.js 15 · React 19 · Tailwind 4 · react-hexgrid", ":3000"),
        ("API", "FastAPI · Uvicorn · Pydantic · python-dotenv", ":8000"),
        ("Graph", "Neo4j 5.26 · neo4j driver · neo4j-graphrag", ":7687 / :7474"),
        ("Agents", "google-adk · LiteLLM · Azure OpenAI or LM Studio", "optional"),
        ("Math", "pandas · pattern catalog · CLV in EUR", "in process"),
        ("Campaigns", "SQLite  artifacts/campaigns.db", "local file"),
    ]
    tb(s, 0.5, 1.5, 2, 0.28, "Piece", 12, MUTED, bold=True)
    tb(s, 2.6, 1.5, 6, 0.28, "Technology", 12, MUTED, bold=True)
    tb(s, 10.6, 1.5, 2.2, 0.28, "Where", 12, MUTED, bold=True, align=PP_ALIGN.RIGHT)
    for i, (piece, tech, where) in enumerate(rows):
        y = 1.85 + i * 0.52
        fill = ICE if i % 2 == 0 else WHITE
        rect(s, 0.45, y, 12.4, 0.48, fill, radius=0.04)
        tb(s, 0.62, y + 0.08, 1.9, 0.32, piece, 14, NAVY, bold=True)
        tb(s, 2.6, y + 0.08, 7.6, 0.32, tech, 14, INK)
        tb(s, 10.2, y + 0.08, 2.45, 0.32, where, 14, TEAL, bold=True, align=PP_ALIGN.RIGHT)

    tb(s, 0.5, 5.1, 12, 0.28, "Artifacts written by step 7", 13, TEAL, bold=True)
    files = "pattern_catalog.json    pincode_profiles.json    diagnoses.json    offers.json    meta.json    campaigns.json"
    tb(s, 0.5, 5.42, 12.3, 0.4, files, 13, INK)
    tb(
        s,
        0.5,
        5.9,
        12.3,
        0.95,
        "Source files in DataSet/: demographics, services, status, location, population, plus the wide churn file. The loader joins them and treats every row as an active customer.",
        14,
        MUTED,
    )
    notes(
        s,
        "Run order for a demo: docker compose up -d in the backend, uv run uvicorn app.main:app --port 8000, "
        "then npm run dev in the UI. If the honeycomb says Offline, NEXT_PUBLIC_API_URL is wrong or the API is down.",
    )

    out = Path(__file__).resolve().parents[1] / "Geo-Analysis-Architecture.pptx"
    prs.save(out)
    return str(out)


if __name__ == "__main__":
    print(build())
