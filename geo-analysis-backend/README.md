# Geo Analysis Backend

FastAPI backend for pincode-level churn risk prediction, area diagnosis, and campaign suggestions.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Docker (for Neo4j)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate

cp .env.example .env
# Set LLM_PROVIDER=azure or lmstudio, then fill the matching credentials
# (Azure OpenAI keys, or LM Studio base URL + model id)

uv sync
docker compose up -d
```

## Run

```bash
uv run uvicorn app.main:app --reload --port 8000
```

API: http://localhost:8000
Docs: http://localhost:8000/docs

## Useful endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/pipeline/status` | Pipeline / artifact load status |
| `POST` | `/pipeline/run` | Build predictions from `DataSet/` CSVs |
| `GET` | `/pincodes` | List area risk scores |
| `GET` | `/pincode/{zip}` | Detail for one pincode |
| `GET` | `/offers` | Offer catalog |
| `GET` / `POST` | `/campaigns` | Campaign storage |

CORS allows the UI at `http://localhost:3000`.
