import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

DATASET_DIR = os.getenv("DATASET_DIR", "DataSet")

OFFERS_PATH = os.getenv("OFFERS_PATH", "app/data/offers.csv")
ARTIFACTS_DIR = os.getenv("ARTIFACTS_DIR", "artifacts")
CAMPAIGNS_DB_PATH = os.getenv("CAMPAIGNS_DB_PATH", "artifacts/campaigns.db")
DIAGNOSIS_TOP_N = _int("DIAGNOSIS_TOP_N", 40)

# Chat LLM provider: "azure" | "lmstudio"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "azure").strip().lower()

AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")

# LM Studio local server — no API key required.
# LiteLLM uses the OpenAI-compatible base (…/v1). Native REST is …/api/v1/chat.
def _lmstudio_openai_base(raw: str) -> str:
    base = (raw or "http://localhost:1234/v1").rstrip("/")
    if base.endswith("/v1"):
        return base
    # Accept host-only values like http://127.0.0.1:1234
    if base.endswith("/api"):
        return f"{base}/v1"
    return f"{base}/v1"


LMSTUDIO_BASE_URL = _lmstudio_openai_base(os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"))
LMSTUDIO_MODEL = os.getenv("LMSTUDIO_MODEL", "")
# OpenAI client libs require a non-empty key string; LM Studio ignores it.
_LMSTUDIO_PLACEHOLDER_KEY = "not-needed"

MIN_N = _int("MIN_N", 30)
SHARE_DELTA = _float("SHARE_DELTA", 0.05)
MEAN_RELATIVE = _float("MEAN_RELATIVE", 0.15)
# Predictive thresholds (rows are treated as still-active customers).
HIGH_RISK_SCORE = _int("HIGH_RISK_SCORE", 65)
LOW_SATISFACTION = _int("LOW_SATISFACTION", 2)

# Telecom CLV: (ARPU × gross_margin) / (monthly_churn + monthly_discount).
# Gross margin is contribution margin (typical European telco service range).
CLV_GROSS_MARGIN = _float("CLV_GROSS_MARGIN", 0.60)
CLV_ANNUAL_DISCOUNT_RATE = _float("CLV_ANNUAL_DISCOUNT_RATE", 0.10)
# Baseline monthly churn by contract (used when individual rate is not applied
# inside CLV — individual risk is applied later via expected_loss = CLV × p).
CLV_MONTHLY_CHURN_MONTH_TO_MONTH = _float("CLV_MONTHLY_CHURN_MONTH_TO_MONTH", 0.030)
CLV_MONTHLY_CHURN_ONE_YEAR = _float("CLV_MONTHLY_CHURN_ONE_YEAR", 0.015)
CLV_MONTHLY_CHURN_TWO_YEAR = _float("CLV_MONTHLY_CHURN_TWO_YEAR", 0.008)
CLV_MONTHLY_CHURN_DEFAULT = _float("CLV_MONTHLY_CHURN_DEFAULT", 0.020)

EMBED_DIM = 128


def llm_ready() -> bool:
    """True when the selected LLM_PROVIDER has the credentials it needs."""
    if LLM_PROVIDER == "lmstudio":
        return bool(LMSTUDIO_BASE_URL and LMSTUDIO_MODEL)
    if LLM_PROVIDER == "azure":
        return bool(AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT)
    return False


# Back-compat alias used by older call sites / status payloads.
azure_ready = llm_ready


def litellm_model() -> str:
    """LiteLLM model id for the active provider."""
    if LLM_PROVIDER == "lmstudio":
        return f"openai/{LMSTUDIO_MODEL}"
    return f"azure/{AZURE_OPENAI_DEPLOYMENT}"


def litellm_call_kwargs() -> dict:
    """Extra kwargs for litellm.completion / ADK LiteLlm (api_base, api_key)."""
    if LLM_PROVIDER == "lmstudio":
        return {
            "api_base": LMSTUDIO_BASE_URL.rstrip("/"),
            "api_key": _LMSTUDIO_PLACEHOLDER_KEY,
        }
    return {}


def apply_litellm_env() -> None:
    if not llm_ready():
        return
    try:
        import litellm

        # Some models reject unsupported params (e.g. low temperature) while reasoning.
        litellm.drop_params = True
    except Exception:  # noqa: BLE001
        pass

    if LLM_PROVIDER == "lmstudio":
        base = LMSTUDIO_BASE_URL.rstrip("/")
        os.environ["OPENAI_API_KEY"] = _LMSTUDIO_PLACEHOLDER_KEY
        os.environ["OPENAI_API_BASE"] = base
        os.environ["OPENAI_BASE_URL"] = base
        return

    os.environ["AZURE_API_KEY"] = AZURE_OPENAI_API_KEY
    os.environ["AZURE_API_BASE"] = AZURE_OPENAI_ENDPOINT.rstrip("/")
    os.environ["AZURE_API_VERSION"] = AZURE_OPENAI_API_VERSION
