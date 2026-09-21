# MineIntel AI

**AI-Powered Mining Document Intelligence & Reporting Platform**  
Smart India Hackathon prototype — **SIH26023**

MineIntel AI turns mining and geological documents (PDF, Excel, scans) into **verified structured facts** and searchable evidence — with human review, contradiction detection, grounded AI answers, geological explorer/analytics, and provenance-preserving reports (HTML / PDF / Excel).

---

## Problem

Mining organizations work with large volumes of production reports, scanned PDFs, exploration reports, and spreadsheets. Critical numbers (production, targets, seam thickness, resources, formations) are hard to find, easy to misread under OCR, and dangerous when an LLM invents values. Teams need a system that:

* ingests both digital and scanned documents
* extracts structured mining **and** geological facts with source evidence
* lets humans correct low-confidence extractions
* detects contradictions across sources
* answers questions only from verified / compatible evidence
* explores geological entities and analytics without inventing chart values
* produces reports with citations in HTML, PDF, and Excel

---

## Solution

MineIntel AI provides an end-to-end pipeline:

* **Ingests** PDF / Excel / image documents with validation (type, size, magic bytes, safe filenames)
* **Handles scanned and digital PDFs** (PyMuPDF text; low-density pages → Tesseract OCR)
* **Extracts structured mining facts** with confidence scores and page/table provenance
* **Classifies & extracts geological facts** (formations, seams, boreholes, resources, thickness/depth) with metric-kind safety
* **Routes low-confidence values** to a human review queue (approve / reject / correct)
* **Validates** reported vs calculated values and cross-document conflicts
* **Indexes** document chunks + structured facts for semantic / hybrid search (RAG)
* **Answers questions** with evidence grounding — the LLM explains; numbers come from structured data
* **Geological Explorer + Analytics** over `GeologicalFact` rows (filters, charts, compare, evidence panel)
* **Analytics & topics** over verified mining structured facts
* **Generates reports** (mining / geological / combined) with HTML, PDF, and Excel export
* **Preserves provenance** (document, page, evidence, fact ID, review status)
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
AI Extraction + Geological Pipeline (G1–G3) + Human Review
  ↓
Structured DB (SQLAlchemy / SQLite) + Vector Index (JSON embeddings)
  ↓
Validation / Metric Compatibility / Evidence Filter
  ↓
RAG + Mining Analytics + Geological Explorer (G4) + Local LLM (Ollama · Qwen)
  ↓
Reports (HTML · PDF · Excel) — Phase 7
```

Local demo stack uses **SQLite + SQLAlchemy** for structured data and a local JSON embedding index for RAG. No cloud API keys are required.

---

## Features

### Core / mining
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

### Geological add-on (G1–G4)
* Document domain classification (geological / exploration vs mining)
* Geological fact extraction with document/page provenance
* Metric-kind compatibility (e.g. minimum workable thickness ≠ seam thickness)
* Formation name quality filters (rejects linguistic “formation” fragments)
* Resource intent + structured resource retrieval
* Selected-document scope for geological Q&A
* **Geological Explorer** — browse formations, seams, boreholes, facts
* **Geological Analytics** — resource by seam, formation→seam, borehole depth, compatible seam thickness
* Document comparison (factual, no ranking)
* Qwen explanation over supplied analytics evidence only

### Reports + security (Phase 7)
* Mining / geological / combined report generation from live application data
* HTML view + download
* **PDF export** (PyMuPDF)
* **Excel export** (openpyxl) with Summary / Facts / Geological / Evidence / Audit sheets
* Review-required values clearly marked; rejected facts excluded
* JWT RBAC (`admin` / `analyst` / `reviewer`) enforced on the backend
* Audit logging (login, uploads, reviews, report generate/export, user changes)
* Document versioning (new upload does not overwrite originals)

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React, TypeScript, Tailwind CSS, Recharts, Vite |
| Backend | Python 3.10–3.12 (3.11 recommended), FastAPI, SQLAlchemy, Pydantic |
| Database (local demo) | SQLite |
| Vector index (local) | Document chunks + JSON embeddings in SQLite |
| OCR / PDF | Tesseract, PyMuPDF, Pillow |
| Excel | pandas, openpyxl |
| Auth | JWT (PyJWT) + bcrypt |
| Local AI | Ollama + Qwen (`qwen2.5:7b` @ `http://127.0.0.1:11434`) |

---

## Project Structure

```
mineintel-ai/
├── backend/                 # FastAPI app
│   └── app/
│       ├── assistant/       # RAG + geological Q&A
│       ├── geology/         # G1–G4 classification, extraction, explorer, analytics
│       ├── reports/         # Report builder + PDF/Excel export
│       ├── routes/          # REST APIs (incl. /geology, /reports)
│       └── ...
├── frontend/                # React SPA
│   └── src/pages/           # Assistant, Geological Explorer, Reports, …
├── tests/                   # Pytest suite (mining + geological + Phase 7)
├── documents/               # Upload root (contents gitignored)
├── .env.example
├── README.md
├── start-backend.ps1
└── start-frontend.ps1
```

---

## Requirements

**Required**

* **Python 3.10, 3.11, or 3.12** — **3.11 recommended**
  * Python **3.9 and older will fail** (`numpy==2.2.x` needs `>=3.10`)
  * Python **3.13** often works; **3.14+** is not yet supported by these pins
* **Node.js** `^20.19` or `>=22.12` (Vite 8 requirement)
* **npm** (ships with Node)
* **Tesseract OCR** (for scanned PDFs/images)

**Optional**

* **Ollama** + model **`qwen2.5:7b`** (local AI Assistant / geological explanations)

Check versions before installing:

```powershell
py -3.11 --version
node --version
```

---

## Installation

### 1. Clone

```powershell
git clone https://github.com/KaustubhaKarthik-cloud/mineintel-ai.git
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
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:PYTHONPATH=(Get-Location).Path
```

macOS / Linux:

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
export PYTHONPATH="$(pwd)"
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

Key pages:

| Page | URL |
|------|-----|
| Dashboard | http://127.0.0.1:5173/ |
| AI Assistant | http://127.0.0.1:5173/assistant |
| Geological Explorer | http://127.0.0.1:5173/geology |
| Reports | http://127.0.0.1:5173/reports |
| Analytics | http://127.0.0.1:5173/analytics |

---

## Local AI Setup

Core document processing, search, analytics, geological explorer, and reports work **without** Ollama.  
Natural-language answers / explanations use Ollama + the configured model when available.

```powershell
ollama serve
ollama pull qwen2.5:7b
ollama list
```

In `.env`:

```
ASSISTANT_LLM_PROVIDER=local_qwen
LOCAL_LLM_BASE_URL=http://127.0.0.1:11434
LOCAL_LLM_MODEL=qwen2.5:7b
```

Check: `GET http://127.0.0.1:8000/api/health/llm` or Settings → AI / Assistant.

**Do not commit model weights.** Pull models locally with Ollama.

---

## Usage

1. Upload a mining or geological document  
2. Processing / OCR runs (geological pipeline classifies + extracts when applicable)  
3. Extraction produces structured facts  
4. Review low-confidence / review-required fields  
5. Run validation for contradictions  
6. Explore mining data or open **Geological Explorer**  
7. Ask the AI Assistant (evidence-grounded; selected-document scope for geology)  
8. Select documents in Analytics for real charts  
9. Generate a **mining / geological / combined** report → HTML / PDF / Excel  
10. Admins manage users and review audit logs  

### Important evidence rules

* The LLM must **not** invent numerical chart or report values  
* **Rejected** facts never appear as verified  
* **Review-required** facts stay clearly marked as pending  
* Incompatible geological metrics are never substituted (e.g. workable thickness ≠ seam thickness)

---

## Security

* **RBAC** enforced on the backend (`admin` / `analyst` / `reviewer`)
* **Passwords** stored with bcrypt (never returned by APIs)
* **JWT** sessions; set `AUTH_REQUIRED=true` for strict mode
* **Audit logs** for login, uploads, reviews, report generate/export, user changes
* **Provenance** on facts, analytics, explorer, and reports
* **Human verification** for low-confidence and conflicting values
* **Secrets**: use `.env` locally; only `.env.example` is committed
* Role permission matrix is visible under Settings (read-only)

---

## API highlights

| Area | Examples |
|------|----------|
| Documents | `/api/documents`, geological facts & pipeline |
| Assistant | `/api/assistant/chat` |
| Geology | `/api/geology/explorer`, `/analytics/*`, `/compare`, `/analytics/explain` |
| Reports | `/api/reports/generate`, `/pdf`, `/excel` |
| Auth / users | `/api/auth/*`, `/api/users` |
| Audit | `/api/system/audit-logs` |

---

## Testing

```powershell
cd mineintel-ai
$env:PYTHONPATH="$((Get-Location).Path);$((Get-Location).Path)\backend"
.\backend\.venv\Scripts\python.exe -m pytest -q
```

Frontend build:

```powershell
cd frontend
npm run build
```

**Latest verified result:** **344 passed**, **3 skipped**, **0 failed**  
(covers mining regression, geological G1–G4, and Phase 7 reports/security).

---

## Screenshots

No committed screenshot assets are included in this repository. Use the running UI at `http://127.0.0.1:5173/` for demos.

---

## License

No project license file is included. Add one if your team/organization requires it before public distribution.
