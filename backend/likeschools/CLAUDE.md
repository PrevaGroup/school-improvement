# likeschools — module guardrails

You are working in the **likeschools** module ("Schools Like You" demographic peer matching).
Read `README.md` here first — it maps every component and reconciles the drifted design docs.

**likeschools is the matching ENGINE. It has no serving surface.** It computes peer sets and
writes them to `mart_school_peer`; that table is its entire contract with the rest of the system.
The `/marts/like-schools` and `/marts/peer-benchmark` endpoints, and the chat tools over them,
belong to the **`serving`** module — they are not yours to change from here. (This reversed an
earlier design where likeschools owned its serving; see the decision in `docs/MODULES.md` and
§4 of `ARCHITECTURE.md`. The short version: `serving` needs `fetch_peer_benchmark` for two other
features, so peer serving living here forced a cross-module import.)

## Scope — what you may touch

- The matching engine: `backend/etl/peers/build_peers.py`.
- This module's owned tables and their models: `feat_match_vector`, `mart_school_peer`,
  `model_partition_stats` — models in `backend/etl/peers/models.py`, DDL in
  `migrations/versions/0004_peer_tables.py`.

That's the module. Everything else is someone else's.

## Hard rules

- **Never read outcome metrics in the matcher.** Match only on `dim_school` *input* demographics
  (spec D1). Reading `fact_metric` outcomes into the match vector breaks the whole premise.
- **`mart_school_peer`'s column shape is the contract.** It is the ONLY thing downstream depends
  on, which is what lets you rewrite the engine freely. Change it only deliberately, and when you
  do, update the DDL, the models, and every reader together (see README step 2).
- **Never import another module, and never let one import you.** `serving` reads
  `mart_school_peer` with SQL; that is the seam. If you find yourself needing a function from
  `app/marts.py` or `app/chat.py`, stop — that's a design smell, raise it.
  `backend/tests/test_module_boundaries.py` fails CI if you try.
- **`dim_school` and the rest of `core` are read-only here.** Don't alter the star schema to suit
  the matcher. If you think you need to, that's a `core` change — flag it, don't do it inline.
- **Models must stay registered.** `etl/peers/models.py` reaches `Base.metadata` only because
  `migrations/env.py` and `0001_initial_schema.py` import it. If you move or rename that module,
  update both — Alembic autogenerate reads a table it can't see as **DROP TABLE**.
  Guarded by `backend/tests/test_schema_inventory.py`.
- **Don't touch the legacy `dim_peer_group` / `peer_group_id` path** unless the task is explicitly
  about removing it. It's a superseded rule/kmeans concept, separate from this Mahalanobis engine.
- **Code over docs.** The `school-classification-*.md` files describe dev alternatives and have
  drifted. Trust `build_peers.py`; if you fix behavior, fix the doc too.

## Definition of done

- The `python -m etl.peers.build_peers --dry-run` path still runs.
- `mart_school_peer` still has the same column shape, or you updated every reader deliberately.
- `python -m pytest` passes from `backend/` (boundary + schema guards included).
- A test covers what you changed.
