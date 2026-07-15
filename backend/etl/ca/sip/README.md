# SIP pipeline — extract → load → serve

The School Improvement Plan (SPSA) pipeline: a district's plan PDFs become structured,
review-ready JSON, load into the DB, and power the chat + attendance/peer marts.

```
raw PDFs (GCS) ──▶ batch_extract ──▶ <school>.json (GCS) ──┬─▶ load_plan_extractions ─▶ plan_extraction (public JSONB)  ◄── the demo reads this
                   (Claude, schema.py)                     └─▶ batch_load ────────────▶ plan / plan_goal / plan_action (private, RLS, tenant-scoped)
```

Run everything in **Cloud Shell** (never the local box — see the deploy notes): the Cloud
SQL Auth Proxy must be up, `GCP_PROJECT` set, and deps installed (`pip install -r
requirements.txt`), from `backend/`.

## ⚠️ Paths — the one thing to get right

Set the prefix **once**, to the folder that holds the PDFs, and derive the rest. Do **not**
append `/sip` again — the PDFs live directly under this prefix, and the JSONs go in its
`extracted/` subfolder.

```bash
export GCP_PROJECT=school-improvement-501916
PREFIX=gs://school-improvement-501916-raw/raw/ca/districts/0622500/sip   # Long Beach; ends in /sip
#   PDFs:      $PREFIX/*.pdf
#   JSON out:  $PREFIX/extracted/*.json
```

(`0622500` is Long Beach Unified's NCES LEAID — same value the DB keys on and the renamed
GCS folder. An earlier `0622710` was a Los Angeles slip; it's gone.)

## 1. Extract — PDFs → reviewable JSON

`--level High` limits to high schools (the demo's focus); drop it for all 77. `--alias`
pins acronym schools the filename can't match. `--skip-existing` makes it a cheap, resumable
run (skips schools whose JSON already exists). Run detached so a Cloud Shell disconnect
can't kill it:

```bash
nohup python -m etl.ca.sip.batch_extract \
  --district-id 0622500 --level High \
  --pdf-prefix "$PREFIX" --out-prefix "$PREFIX/extracted" \
  --plan-year 2025-26 --context-file etl/ca/sip/contexts/lbusd_spsa.txt \
  --alias CAMS=062250009901 --skip-existing > ~/extract.log 2>&1 &
tail -f ~/extract.log        # last line "done: N extracted, M skipped …" = finished
```

Cost/time: ~$0.85 and ~1–2 min per school (PDF dominates input tokens). `--skip-existing`
re-spends only on the missing ones. Confirm the harvest:

```bash
gcloud storage ls "$PREFIX/extracted/*.json" | wc -l
```

## 2. Load — pick the right target

**Two loaders, two tables. The demo (chat, attendance mart, peer benchmark) reads
`plan_extraction`, so `load_plan_extractions` is the one you almost always want.**

| Loader | Writes | Tier | When |
|---|---|---|---|
| `load_plan_extractions` | `plan_extraction` (full JSONB doc) | **public** | **Serving the demo** — keeps provenance, funding text, all metric links |
| `batch_load` | `plan` / `plan_goal` / `plan_action` | private (RLS, tenant) | The normalized augment layer; lossy (one metric/goal); needs `--tenant` |

For the demo:
```bash
python -m etl.ca.sip.load_plan_extractions --in-prefix "$PREFIX/extracted"
```

Optional — the normalized augment layer under a tenant (not needed for the chat/marts):
```bash
python -m etl.ca.sip.batch_load --tenant lbusd --display-name "Long Beach Unified" \
  --in-prefix "$PREFIX/extracted" --force
```

Verify `plan_extraction` (public — no `SET app.tenant` needed):
```bash
python - <<'PY'
import sys; sys.path.append('.')
from sqlalchemy import text
from etl.ca._shared import _engine
with _engine().connect() as c:
    print("plan_extraction rows:", c.execute(text("SELECT count(*) FROM plan_extraction")).scalar())
PY
```

## 3. Serve

Once `plan_extraction` is populated (and, for peer comparison, `likeschools/build_peers` has
run), the app surfaces it:

- `GET /` — the chat UI (level selector; asks over the plans + peers)
- `POST /chat` — grounded Q&A (tools: attendance plans, find_similar_schools, compare_to_peers)
- `GET /marts/attendance-plans`, `/marts/like-schools`, `/marts/peer-benchmark`

Smoke-test locally in Cloud Shell (Web Preview → port 8080): `uvicorn app.main:app --port 8080`.
Deploy behind Cloud Run IAM per `../../../DEPLOY.md`.
