# scoring

The immutable record of what was scored, by whom, under which configuration, and what a teacher
then decided. Three tables and a state machine enforced in the database.

Read `CONTRACT.md` before changing a table shape. The short version: scores append and never
update, only a teacher can release, and an override is not a supersession.

Design: the SIP teacher-subsystem expansion plan §6, and agentic-scoring-pipeline-design v0.06
§3.2 (states) and §6.1 (the score record).

## Running the pipeline

From Cloud Shell, with the Cloud SQL Auth Proxy up (`backend/DEPLOY.md`). Never from a
workstation — this connects as the migrator role, like every producer job.

```bash
cd backend
python -m scoring.seed_demo --text-dir /tmp/sip-demo   # registry + 2 synthetic papers, bound
python -m scoring.run_scoring --config-key demo-writing --dry-run   # calls the model, writes nothing
python -m scoring.run_scoring --config-key demo-writing            # scores, writes, transitions
python -m scoring.seed_demo --purge                    # remove every demo- row
```

`--dry-run` still spends money: it makes every model call and discards the result. That is the
point of it — the thing worth rehearsing is the calls and the assembly, not the INSERT.

Twelve calls per paper at most (six criteria, two stages), fewer when a criterion has no verified
evidence and stage D is skipped.

## What has and has not been exercised

| | |
|---|---|
| Unit tests | scripted rater, no network — the prompt-assembly absences, the outcome mapping, the row |
| `sql/20_scoring_smoketest.sql` | the triggers, provoked against real Postgres and rolled back |
| `seed_demo` + `run_scoring` | the only path that has made a model call and moved an artifact |

A trigger created without error says nothing about whether it fires, and a pipeline that passes its
tests says nothing about whether it runs. Those are three different claims and they need three
different kinds of evidence.
