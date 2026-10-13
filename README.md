 Churn Prevention Using Geo Location

Churn Prevention is an AI-assisted geo-analysis project that identifies high-risk customer churn areas and helps teams prioritize retention actions by location.

The project combines a FastAPI backend, a Next.js frontend, customer churn analytics, pincode-level aggregation, campaign recommendations, and optional Neo4j/LLM-backed intelligence.

## What It Does

This project helps analyze churn risk geographically.

It can:

- Load telco churn data from local CSV files
- Aggregate churn risk by pincode / ZIP code
- Identify high-risk regions and customer segments
- Show churn hotspots in a visual UI
- Provide area-level diagnosis for why churn is likely
- Recommend retention offers or campaigns
- Store campaign history locally
- Optionally use Neo4j for graph-based relationship analysis
- Optionally use Azure OpenAI or LM Studio for AI-generated explanations

## Project Structure

```text
Churn Prevention/
  geo-analysis-backend/
    app/
    tests/
    scripts/
    README.md
    pyproject.toml
    docker-compose.yml

  geo-analysis-ui/
    app/
    components/
    lib/
    demo-recordings/
    README.md
    package.json

Backend
The backend is built with FastAPI.
Main responsibilities:
Load and process churn datasets
Calculate pincode-level churn metrics
Generate risk scores
Build customer and area profiles
Manage offers and campaign suggestions
Expose REST APIs for the frontend
Integrate with Neo4j for graph storage and search
Integrate with LLM providers when configured
Backend details are in:
geo-analysis-backend/README.md

Frontend
The frontend is built with Next.js.
Main features:
Geo/pincode churn risk dashboard
Honeycomb-style risk visualization
Area studio for detailed churn diagnosis
Offer and campaign views
Backend status and pipeline controls
Frontend details are in:
geo-analysis-ui/README.md

Data
Dataset files are not committed to this repository.
Place local CSV files in:
geo-analysis-backend/DataSet/

This folder is intentionally ignored by git to avoid committing customer or dummy data.
Environment Variables
Secrets and local configuration are not committed.
Use the backend example file:
geo-analysis-backend/.env.example

Create a local .env file inside geo-analysis-backend/ and configure values such as:
NEO4J_URI=
NEO4J_USER=
NEO4J_PASSWORD=

AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_VERSION=
AZURE_OPENAI_DEPLOYMENT=

The .env file is ignored by git.
Running Locally
Backend
cd "Churn Prevention/geo-analysis-backend"
uv sync
docker compose up -d
uv run uvicorn app.main:app --reload --port 8000

Backend API:
http://localhost:8000

API docs:
http://localhost:8000/docs

Frontend
cd "Churn Prevention/geo-analysis-ui"
npm install
npm run dev

Frontend app:
http://localhost:3000

Demo
A demo recording is available at:
geo-analysis-ui/demo-recordings/DEMO_Idea.mov

Notes
Local secrets are excluded from git.
Dataset files are excluded from git.
Generated artifacts are excluded from git.
Neo4j credentials must be supplied through local environment variables.
LLM functionality is optional and depends on local configuration.
