# MineIntel AI

**AI-Powered Mining Document Intelligence & Reporting Platform**  
Smart India Hackathon prototype — **SIH26023**

MineIntel AI turns mining and geological documents (PDF, Excel, scans) into **verified structured facts** and searchable evidence — with human review, contradiction detection, grounded AI answers, analytics, and provenance-preserving reports.

---

## Problem

Mining organizations work with large volumes of production reports, scanned PDFs, and spreadsheets. Critical numbers (production, targets, entity names, periods) are hard to find, easy to misread under OCR, and dangerous when an LLM invents values. Teams need a system that:

* ingests both digital and scanned documents
* extracts structured mining facts with source evidence
* lets humans correct low-confidence extractions
* detects contradictions across sources
* answers questions only from verified evidence
* produces analytics and reports with citations

---

## Solution

MineIntel AI provides an end-to-end pipeline:

* **Ingests** PDF / Excel / image documents with validation (type, size, magic bytes, safe filenames)
* **Handles scanned and digital PDFs** (PyMuPDF text; low-density pages → Tesseract OCR)
* **Extracts structured facts** with confidence scores and page/table provenance
* **Routes low-confidence values** to a human review queue (approve / reject / correct)
* **Validates** reported vs calculated values and cross-document conflicts
* **Indexes** document chunks + structured facts for semantic / hybrid search (RAG)
* **Answers questions** with evidence grounding — the LLM summarizes; numbers come from verified data
* **Analytics & topics** over verified structured facts (document selection supported)
* **Generates stored HTML reports** with executive summary, metrics, discrepancies, and citations
* **Preserves provenance** (document, page, table / source location)
* **RBAC + audit logs + document versioning** for accountable operations

---

## Architecture

```
User
  ↓
Frontend (React + TypeScript + Vite)
  ↓
FastAPI Backend
  ↓
Document Ingestion
  ↓
OCR / Document Parsing (Tesseract · PyMuPDF · pandas/openpyxl)
  ↓
AI Extraction + Human Review
  ↓
Structured DB (SQLAlchemy / SQLite) + Vector Index (JSON embeddings)
  ↓
Validation / Evidence Compatibility Layer
  ↓
RAG + Analytics + Local LLM (Ollama · Qwen)
  ↓
Reports (HTML, stored + downloadable)
```

---

## Features

* Document upload and processing (PDF, Excel, images)
* OCR for scanned pages
* AI extraction with confidence scoring
* Human review and correction history (original AI value preserved)
* Validation / contradiction detection
* Structured facts warehouse
* Semantic search / RAG with citations
* Evidence-grounded AI Assistant
* Analytics (trends, compare, actual vs target) from verified data
* Topics extraction
* Report generation, storage, view, download + provenance
* JWT RBAC (admin / analyst / reviewer)
* Audit logging
* Document versioning (new upload does not overwrite originals)
* Local AI via Ollama (`qwen2.5:7b`) with graceful degrade when unavailable

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React, TypeScript, Tailwind CSS, Recharts, Vite |
| Backend | Python 3.11, FastAPI, SQLAlchemy, Pydantic |
| Database (local demo) | SQLite |
| Optional DB | PostgreSQL (Docker Compose available; pgvector-ready dependency present) |
| Vector index (local) | Document chunks + JSON embeddings in SQLite |
| OCR / PDF | Tesseract, PyMuPDF, Pillow |
| Excel | pandas, openpyxl |
| Auth | JWT (PyJWT) + bcrypt |
| Local AI | Ollama + Qwen (`qwen2.5:7b` @ `http://127.0.0.1:11434`) |

---

## Project Structure

```
mineintel-ai/
├── backend/           # FastAPI app, services, OCR, RAG, analytics, auth
├── frontend/          # React SPA
├── tests/             # Pytest suite
├── database/          # Optional Postgres init scripts
├── documents/         # Upload root (contents gitignored; .gitkeep kept)
├── .env.example       # Safe configuration template
├── .gitignore
├── README.md
├── docker-compose.yml # Optional Postgres
├── start-backend.ps1
└── start-frontend.ps1
```

---

## Requirements

Verified on this project:

* **Python** 3.11.x
* **Node.js** 24.x (Vite frontend; other modern Node LTS versions typically work)
* **npm** (ships with Node)
* **Tesseract OCR** (for scanned PDFs/images)
* **Ollama** (optional for local AI Assistant) + model **`qwen2.5:7b`**

---

## Installation

### 1. Clone

```powershell
git clone <YOUR_REPO_URL> mineintel-ai
cd mineintel-ai
```

### 2. Configure environment

```powershell
copy .env.example .env
# Edit SECRET_KEY and TESSERACT_CMD as needed
```

### 3. Backend dependencies

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH=(Get-Location).Path
```

### 4. Frontend dependencies

```powershell
cd ..\frontend
npm install
```

### 5. Database

Tables are created automatically on backend startup (`init_db`).  
With `AUTH_SEED_USERS=true`, demo users are seeded (change passwords before any shared deploy):

| Username | Password | Role |
|----------|----------|------|
| admin | admin123 | admin |
| analyst | analyst123 | analyst |
| reviewer | reviewer123 | reviewer |

### 6. Start backend

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH=(Get-Location).Path
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Or from repo root: `.\start-backend.ps1`

### 7. Start frontend

```powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Or: `.\start-frontend.ps1`

Open **http://127.0.0.1:5173/**

---

## Local AI Setup

Core document processing, search, analytics, and reports work **without** Ollama.  
The AI Assistant’s local LLM path requires Ollama + the configured model.

```powershell
# 1. Install Ollama from https://ollama.com
# 2. Start the Ollama service
ollama serve

# 3. Pull the model used by this project
ollama pull qwen2.5:7b

# 4. Verify
ollama list
```

In `.env`:

```
ASSISTANT_LLM_PROVIDER=local_qwen
LOCAL_LLM_BASE_URL=http://127.0.0.1:11434
LOCAL_LLM_MODEL=qwen2.5:7b
```

Then start MineIntel and check:

* `GET http://127.0.0.1:8000/api/health/llm`
* Settings → AI / Assistant

**Do not commit model weights.** Pull models locally with Ollama.

---

## Usage

1. Upload a mining document  
2. Processing / OCR runs  
3. Extraction produces structured facts  
4. Review low-confidence fields  
5. Run validation for contradictions  
6. Explore / semantic search  
7. Ask the AI Assistant (evidence-grounded)  
8. Select documents in Analytics for real charts  
9. Generate a report → open / download  
10. Admins review audit logs  

---

## Security

* **RBAC** enforced on the backend (`admin` / `analyst` / `reviewer`)
* **Passwords** stored with bcrypt (never returned by APIs)
* **JWT** sessions; set `AUTH_REQUIRED=true` for strict mode
* **Audit logs** for login, uploads, reviews, reports, user changes
* **Provenance** on facts, analytics, and reports
* **Human verification** for low-confidence and conflicting values
* **Secrets**: use `.env` locally; only `.env.example` is committed

---

## Testing

```powershell
cd mineintel-ai
$env:PYTHONPATH="C:\path\to\mineintel-ai\backend;C:\path\to\mineintel-ai"
$env:AUTH_REQUIRED="false"
.\backend\.venv\Scripts\pytest.exe tests -q
```

Frontend build:

```powershell
cd frontend
npm run build
```

**Latest verified result:** **161 passed** (full `tests/` suite).

---

## Screenshots

No committed screenshot assets are included in this repository. Use the running UI at `http://127.0.0.1:5173/` for demos.

---

## License

No project license file is included. Add one if your team/organization requires it before public distribution.
