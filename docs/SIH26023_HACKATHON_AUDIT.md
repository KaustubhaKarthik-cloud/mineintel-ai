# SIH 26023 APPLICATION AUDIT

**Date:** 2026-09-22  
**Scope:** Forensic inventory only — **no production code changes applied in this pass**.  
**DB inspected:** `backend/mineintel_demo.db` (SQLite)  
**Method:** Code search + live `TestClient` API probes + SQL inspection + Ollama probe.

---

## 1. Existing Features (complete inventory)

### Frontend routes (`frontend/src/App.tsx` + Sidebar)

| Route | Page | Nav label | Nav permission gate |
|-------|------|-----------|---------------------|
| `/login` | LoginPage | (public) | — |
| `/` | DashboardPage | Dashboard | none |
| `/documents` | DocumentsPage | Documents | `documents.read` |
| `/documents/:id` | DocumentDetailPage | (detail) | via documents |
| `/upload` | UploadPage | Upload | `documents.upload` |
| `/review` | ReviewPage | Review Queue | `review.act` |
| `/validation` | ValidationPage | Validation | **`documents.read`** ⚠️ |
| `/search` | SearchPage | Semantic Search | `search` |
| `/explorer` | ExplorerPage | Data Explorer | `explore` |
| `/geology` | GeologicalExplorerPage | Geological Explorer | `explore` |
| `/assistant` | AssistantPage | AI Assistant | `assistant` |
| `/analytics` | AnalyticsPage | Analytics | `analytics` |
| `/topics` | TopicsPage | Topics | `topics` |
| `/reports` | ReportsPage | Reports | `reports.read` |
| `/reports/:id` | ReportDetailPage | (detail) | reports |
| `/audit` | AuditPage | Audit Logs | `audit.read` |
| `/users` | UsersPage | Users | `users.manage` |
| `/settings` | SettingsPage | Settings | `settings.read` |

**Not found anywhere:** “Schematic Search” (no component, route, API, or string). Closest: **Semantic Search** (`/search`) and **Data Explorer** (`/explorer`).

### Backend API surface (`/api/...`)

| Prefix | Auth enforcement today |
|--------|------------------------|
| `/auth` | login/me/logout |
| `/users` | `users.manage` ✅ |
| `/documents` | mixed (`documents.read/upload/review.act`) ✅ mostly |
| `/reviews` | `review.act` ✅ |
| `/geology/*` | `explore` / `analytics` / `assistant` ✅ |
| `/reports` | reports.* ✅ |
| `/system/status` | authenticated user |
| `/system/audit-logs` | `audit.read` ✅ |
| `/validation/*` | **NONE** ❌ open |
| `/analytics/*` | **NONE** ❌ open |
| `/assistant/*` | **NONE** ❌ open |
| `/search` | **NONE** ❌ open |
| `/explore/*` | **NONE** ❌ open |
| `/topics/*` | **NONE** ❌ open |
| `/dashboard` | **NONE** ❌ open (blends demo stats) |

### Live DB snapshot (hackathon machine)

| Table | Count |
|-------|------:|
| users | 3 |
| documents | 17 |
| geological_facts | 1390 |
| extracted_facts | 20 |
| document_chunks | 10925 |
| review_items | 1331 |
| validation_conflicts | 11 |
| reports | 12 |

Users: `admin` / `analyst` / `reviewer` (all active).

---

## 2. Role / Access Matrix

### Current roles (code + seed)

Defined in `backend/app/models/__init__.py` `UserRole`:
- `admin`
- `analyst`
- `reviewer`

Seeded in `backend/app/auth/seed.py` + LoginPage demo cards (`admin123` / `analyst123` / `reviewer123`).

**Critical:** `AUTH_REQUIRED=false` (default). Unauthenticated `/api/auth/me` returns:

```
role=analyst, username=ops.analyst, anonymous=true
permissions include: review.act, analytics, assistant, documents.upload, reports.*, …
```

(`backend/app/auth/deps.py` `get_current_user`)

### Permission map (current `ROLE_PERMISSIONS`)

| Permission | Admin | Analyst | Reviewer | Desired USER | Desired ADMIN |
|------------|:-----:|:-------:|:--------:|:------------:|:-------------:|
| documents.read | ✓ | ✓ | ✓ | ✓ | ✓ |
| documents.upload | ✓ | ✓ | | ✓ | ✓ |
| documents.delete/version | ✓ | | | | ✓ |
| review.act | ✓ | ✓ ⚠️ | ✓ | | ✓ |
| validation.act | ✓ | | ✓ | | ✓ |
| search / explore | ✓ | ✓ | ✓ (explore+search) | ✓ | ✓ |
| analytics / topics / assistant | ✓ | ✓ | | ✓ | ✓ |
| reports.read | ✓ | ✓ | ✓ | ✓ | ✓ |
| reports.generate/delete | ✓ | ✓ | | | ✓ |
| users.manage / audit.read / system.configure | ✓ | | | | ✓ |
| settings.read | ✓ | ✓ | ✓ | limited | ✓ |

### Why Reviewer sees Validation (root cause — confirmed)

1. **Sidebar** gates Validation with `documents.read` (not `validation.act`) → Reviewer has `documents.read` → nav shows Validation.  
2. **`ROLE_PERMISSIONS[reviewer]` includes `validation.act`** by design today.  
3. **`/api/validation/*` has zero `require_permission`** → even Analyst (no `validation.act`) got **HTTP 200** on `/api/validation/stats` in live probe.

Frontend hide ≠ security. Backend is the broken layer for validation/analytics/assistant/search/explore/topics.

---

## 3. Working Status (end-to-end)

| Feature | Status | Evidence |
|---------|--------|----------|
| Login (3 roles) | WORKING | Seed + `/api/auth/login` |
| Anonymous demo browse | WORKING (undesired) | `/me` → analyst |
| Document list/upload | WORKING | 17 docs in DB |
| Review Queue | WORKING | 1331 review_items; geo sync exists; `/api/reviews` 200 |
| Validation UI | PARTIAL | UI loads; APIs open; conflicts exist (11) |
| Semantic Search | PARTIAL/UNKNOWN UX | API open; mock embeddings (`EMBEDDING_PROVIDER=mock`) |
| Data Explorer | PARTIAL | APIs open; structured facts present |
| Geological Explorer | PARTIAL | `/api/geology/explorer` 200; noisy OCR seams; no map |
| AI Assistant | WORKING when evidence exists | CIL March FY25 → 85.81 MT; `llm.called=True`, provider `local_qwen`/`qwen2.5:7b` |
| AI Assistant (no evidence) | WORKING (refusal) | formations listing → `llm.called=False`, reason `no_evidence` |
| Analytics overview | WORKING | KPIs 200; 210 entities |
| Analytics charts (default filters) | PARTIAL / LOOKS BROKEN | Auto-picks bad first entity → empty series + warnings |
| Analytics charts (CIL + coal + March) | WORKING | Trend returns FY2024/FY2025 values with provenance |
| Topics | UNKNOWN/PARTIAL | APIs unguarded; depends on topic extraction |
| Reports | WORKING (RBAC on generate) | 12 reports; analyst can generate; reviewer read-only generate blocked in tests |
| Users / Audit | WORKING for admin | users 200 admin / 403 others; audit at `/api/system/audit-logs` |
| OCR / Paddle | PRESENT | Integrated; suite forces Tesseract in tests |
| Dashboard | PARTIAL / MOCK BLEND | Merges `demo_data.get_dashboard_stats()` with live docs |
| Schematic Search | N/A — DOES NOT EXIST | No code references |

---

## 4. Broken / Partial Features — root causes

### A. Reviewer “admin-like” access
- **Files:** `Sidebar.tsx` (Validation → `documents.read`); `auth/deps.py` (reviewer has `validation.act`); `routes/validation.py` (no auth).
- **First broken layer:** Backend authorization missing on validation (+ wrong frontend permission for nav).

### B. Analyst can Review Queue
- **File:** `auth/deps.py` — Analyst includes `review.act`.
- Against desired model (review = ADMIN only): **misconfigured RBAC**.

### C. Analytics “doesn’t work / charts empty”
- **Not a dead API.** `/api/analytics/*` returns 200.
- **UX/data selection:** page auto-selects first entity alphabetically (`AAD (AMALGAMED A…`) and can query metrics with no verified pairs → `data: []`, `warnings: Insufficient verified…`.
- **Correct path works:** entity=`CIL`, metric=`coal`, month=`March` → real chart data.
- **Also:** analytics requires verified/index structured facts; many `extracted_facts` are still `high_confidence`/`extracted` (not approved) — charts lean on `structured_fact` chunks (7072).

### D. AI Assistant “may not respond”
- **Config:** `ASSISTANT_LLM_PROVIDER=local_qwen`, model `qwen2.5:7b`.
- **Ollama:** reachable; models include `qwen2.5:7b` and `deepseek-r1:7b`.
- **When evidence exists:** LLM called successfully.
- **When no evidence:** intentional refusal (not a crash) — can look “broken” in UI if user asks vague geo questions without doc scope.
- **Routes unauthenticated** — anyone can call assistant.

### E. Geological “Korea”
- **NOT South Korea / fabricated map.**
- Live evidence text: `DISTRICT : KOREA, CHHATTISGARH` — **Korea district, India**, Sonhat Coalfield, North of Labji-Pusla Block (G3 report).
- No map/GeoJSON/Korea hardcode in frontend.
- Separate quality issue: dirty seam labels (`Seam s`, `Seam is`, `Seam Name`, `Seam INTERSECTION`, formation `in Barakar Formation`) from OCR/extraction noise (1390 facts, mostly `review_required`).

### F. Schematic Search
- **Does not exist.** Confirm with team whether they mean Semantic Search or Data Explorer before deleting anything.

---

## 5. AI Assistant (forensic)

```
UI AssistantPage → POST /api/assistant/chat → ask_assistant
  → query_router / retrievers / evidence_builder
  → LocalQwenProvider (Ollama) OR mock fallback
  → reply + sources + warnings + llm metadata
```

| Check | Result |
|-------|--------|
| Endpoint exists | Yes |
| Auth on endpoint | **No** |
| Provider configured | `local_qwen` |
| API key required | No (local Ollama) |
| Ollama up | Yes |
| Model present | `qwen2.5:7b` yes |
| Retrieval | Yes (structured + RAG) |
| LLM receives context | Yes when evidence found |
| Frontend field | uses `reply` |
| Fake success path | Mock only if provider mock / LLM error fallback templates |

---

## 6. Analytics (forensic)

| Chart/API | Status | Notes |
|-----------|--------|-------|
| Overview KPIs | WORKING | Live verified/index data |
| Dimensions | WORKING | 210 entities, 10 metrics, 17 docs |
| Trend (bad default entity) | EMPTY | Looks broken |
| Trend (CIL/coal/March) | WORKING | Real values + provenance |
| Actual vs target (bad entity) | EMPTY | warnings |
| Compare (bad entities) | EMPTY | warnings |
| Auth | MISSING | open API |
| Mock charts in UI | No (Recharts on API data) | Dashboard still blends demo stats |

---

## 7. Geological Explorer

- Charts only (Recharts) — **no geographic map component** in repo.
- “Korea” = **Korea district, Chhattisgarh** in source report evidence (keep; clarify in UI).
- Noise entities from extraction should be filtered/reviewed, not geocoded.

---

## 8. Authentication summary

| Item | Location |
|------|----------|
| Roles enum | `models.UserRole` |
| Permissions | `auth/deps.py` `ROLE_PERMISSIONS` |
| JWT | `auth/security.py` |
| Seed users | `auth/seed.py` |
| Login UI roles | `LoginPage.tsx` DEMO_ROLES |
| Frontend gate | `AuthContext.hasPermission` + Sidebar |
| Backend gate | inconsistent — many routers unprotected |
| Default anonymous | **analyst** when `auth_required=false` |

---

## 9. Features to Remove (proposed — not done yet)

| Item | Action | Risk |
|------|--------|------|
| Role `analyst` | Migrate → `user` or `admin`; remove from seed/login | Medium — update DB users + tests |
| Role `reviewer` | Migrate → `admin` (or limited admin) | Medium |
| “Schematic Search” | **Nothing to delete** unless alias identified | None |
| `frontend/src/data/demo.ts` MOCK_* | Keep for offline story; stop blending into live dashboard unlabeled | Low |
| `demo_data.DEMO_*` fallbacks in reviews/dashboard | Reduce for hackathon when DB has data | Medium |
| Dirty geo seam noise | Cleanup/filter — not “Korea removal” | Medium (G1–G4) |

---

## 10. Features to Fix (hackathon priority)

### P0
1. Collapse RBAC to **USER + ADMIN** only  
2. Enforce `require_permission` on validation, analytics, assistant, search, explore, topics, dashboard  
3. Fix Validation nav permission → `validation.act` (admin-only)  
4. Set `AUTH_REQUIRED=true` for hackathon (or anonymous → least-privilege user with **no** review)  
5. Analytics UX: smarter default entity/metric (prefer CIL/coal/production with data); empty-state copy  
6. Clarify Korea district in geo evidence labels (not country)

### P1
7. Remove analyst/reviewer from Login demo cards  
8. Migrate DB roles  
9. Confirm Semantic Search vs “Schematic” with stakeholders  
10. Tighten Review Queue to ADMIN only  

### P2
11. Dashboard stop unlabeled demo blend  
12. Geo fact quality filters for garbage seam names  
13. Docs / settings role matrix update  

---

## 11. Recommended Fix Order

1. Auth model + seed + Login UI (USER/ADMIN)  
2. Backend `require_permission` on all open routers  
3. Sidebar permission fixes  
4. Anonymous policy (`auth_required` or weak user)  
5. Analytics empty-state / defaults  
6. Geo labeling (Korea district) + optional noise filter  
7. Remove obsolete role references in tests last  
8. Full pytest + manual USER/ADMIN login matrix  

**Do not** touch OCR/Paddle/G1–G4 extractors unless geo noise cleanup is scoped carefully.

---

## 12. Files Affected (for upcoming fix pass)

- `backend/app/auth/deps.py`, `seed.py`, `models` (`UserRole`)  
- `backend/app/routes/validation.py`, `analytics.py`, `assistant.py`, `search.py`, `explore.py`, `topics.py`, `dashboard.py`  
- `frontend/src/pages/LoginPage.tsx`, `components/Sidebar.tsx`, `pages/AnalyticsPage.tsx`, possibly GeologicalExplorer empty/labels  
- `tests/test_phase7_reports_geo.py` and any role-hardcoded tests  
- `.env` / `.env.example` (`AUTH_REQUIRED`)

---

## 13. Database Changes (planned)

- Migrate `users.role`: `analyst`→`user`, `reviewer`→`admin` (or explicit mapping)  
- Optionally add `user` to `UserRole` enum  
- No need to delete geological facts containing “KOREA, CHHATTISGARH”

---

## 14. API Changes (planned)

- Add `Depends(require_permission(...))` to currently open routers  
- Possibly rename permissions for clarity (`validation.act` admin-only)  
- No schematic endpoints to remove  

---

## 15. Risk Assessment

| Change | Risk to G1–G4 |
|--------|----------------|
| RBAC / auth_required | Low if tests updated |
| Guarding analytics/assistant APIs | Low |
| Analytics default entity UX | Low |
| Deleting Korea facts | **HIGH / WRONG** — real district |
| Aggressive geo noise deletion | Medium — may remove valid seams |
| OCR/Paddle edits | Avoid for hackathon unless broken |

---

## Probe log (abridged)

- Anon `/api/auth/me` → analyst + `review.act`  
- Reviewer + Analyst → `/api/reviews` 200; `/api/validation/stats` 200 (even without permission for analyst)  
- Unauthenticated `/api/validation/stats`, `/api/analytics` → 200  
- Assistant CIL query → grounded 85.81 MT, LLM called  
- Analytics CIL/coal/March → non-empty chart  
- Ollama `qwen2.5:7b` available  

---

## Deliberately NOT changed (this pass)

Everything. Per instructions: audit first, no mass refactor/deletion until this report is accepted—especially before touching “Korea” or inventing a Schematic Search delete.
