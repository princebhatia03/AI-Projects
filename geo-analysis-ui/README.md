# Geo Analysis UI

Next.js frontend for the geo / pincode churn analysis workspace (honeycomb risk map and area studio).

## Prerequisites

- Node.js 20+
- Backend running at http://localhost:8000 (see `geo-analysis-backend`)

## Setup

```bash
npm install
```

Optional: set a custom API base URL (defaults to `http://localhost:8000`):

```bash
# .env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Run

```bash
npm run dev
```

App: http://localhost:3000

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Dev server with hot reload |
| `npm run build` | Production build |
| `npm start` | Serve the production build |

## Backend dependency

Start the API first:

```bash
cd ../geo-analysis-backend
uv run uvicorn app.main:app --reload --port 8000
```

If the honeycomb shows **Offline**, the UI cannot reach the backend at `NEXT_PUBLIC_API_URL`.
