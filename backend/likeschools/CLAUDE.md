# likeschools — module guardrails

You are working in the **likeschools** module ("Schools Like You" demographic peer matching).
Read `README.md` here first — it maps every component and reconciles the drifted design docs.

## Scope — what you may touch

- The matching engine: `backend/etl/peers/build_peers.py`.
- This module's owned tables: `feat_match_vector`, `mart_school_peer`, `model_partition_stats`
  (DDL in `migrations/versions/0004_peer_tables.py`, models in `app/models/reference.py` for now).
- The peer serving code in `app/marts.py` (`fetch_like_schools`, `fetch_peer_benchmark`, the
  `/like-schools` and `/peer-benchmark` endpoints) and the chat tools that wrap it in `app/chat.py`.

## Hard rules

- **Never read outcome metrics in the matcher.** Match only on `dim_school` *input* demographics
  (spec D1). Reading `fact_metric` outcomes into the match vector breaks the whole premise.
- **`mart_school_peer`'s column shape is the contract.** Change it only deliberately, and when you
  do, update the DDL, the ORM models, and every downstream reader together (see README step 2).
- **`dim_school` and the rest of `core` are read-only here.** Don't alter the star schema to suit
  the matcher. If you think you need to, that's a `core` change — flag it, don't do it inline.
- **Don't touch the legacy `dim_peer_group` / `peer_group_id` path** unless the task is explicitly
  about removing it. It's a superseded rule/kmeans concept, separate from this Mahalanobis engine.
- **Code over docs.** The `school-classification-*.md` files describe dev alternatives and have
  drifted. Trust `build_peers.py`; if you fix behavior, fix the doc too.

## Definition of done

- The `python -m etl.peers.build_peers --dry-run` path still runs.
- Downstream `/like-schools` and `/peer-benchmark` still return the same shape (or you updated all
  consumers deliberately).
- A test covers what you changed.
