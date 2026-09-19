#!/usr/bin/env bash
# Roll out student-work access control (#149-#151) to production. Run in CLOUD SHELL:
#
#   cd ~/school-improvement && git fetch origin && git checkout main && git pull
#   bash backend/scripts/rollout_writing_access.sh you@prevagroup.com
#
# Every credential comes from Secret Manager, the same way the migration runbook reads
# `sip-migrator-password`; nothing is typed and nothing is printed. It needs one secret that
# predates it, `postgres-password` (the Cloud SQL admin), because creating roles is the one step
# the migrator cannot do.
#
# Idempotent: re-running after a failure picks up where it stopped. Order matters —
# secret -> roles -> migrate -> prove -> grant -> deploy -> job. Between the migration and the
# deploy (a few minutes) the review console errors, because the old revision's sip_app no longer
# reaches the moved tables. SIP itself is unaffected throughout.
set -euo pipefail

EMAIL="${1:?usage: rollout_writing_access.sh <the email you sign in to SIP with>}"
PROJECT=school-improvement-501916
ICN=school-improvement-501916:us-central1:school-improvement-sql
REGION=us-central1
SECTION=section-11b-period4

secret() { gcloud secrets versions access latest --secret="$1" --project "$PROJECT"; }
has_secret() { gcloud secrets describe "$1" --project "$PROJECT" >/dev/null 2>&1; }
say() { printf '\n== %s\n' "$*"; }

# ---- 0. From a clean, current main. A rollout of anything else is a different rollout.
cd "$(git rev-parse --show-toplevel)"
git fetch -q origin
[[ "$(git rev-parse --abbrev-ref HEAD)" == main ]] || { echo "check out main first"; exit 1; }
[[ -z "$(git status --porcelain)" ]] || { echo "working tree is not clean"; exit 1; }
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || { echo "git pull first"; exit 1; }
say "code: $(git log --oneline -1)"

has_secret postgres-password || { echo "postgres-password is not in Secret Manager yet"; exit 1; }

if ! pgrep -f "cloud-sql-proxy.*$ICN" >/dev/null; then
  cloud-sql-proxy "$ICN" --port 5432 > /tmp/cloud-sql-proxy.log 2>&1 &
  for _ in $(seq 30); do grep -q "ready for new connections" /tmp/cloud-sql-proxy.log && break; sleep 1; done
fi
export GCP_PROJECT=$PROJECT DB_HOST=127.0.0.1 DB_PORT=5432 DB_NAME=sip
as_admin()    { PGPASSWORD=$(secret postgres-password)     psql "host=127.0.0.1 dbname=sip user=postgres"     -v ON_ERROR_STOP=1 -q "$@"; }
as_migrator() { PGPASSWORD=$(secret sip-migrator-password) psql "host=127.0.0.1 dbname=sip user=sip_migrator" -v ON_ERROR_STOP=1 -q "$@"; }

# ---- 1. writing_app's password: minted once, straight into Secret Manager, never shown.
if has_secret writing-app-password; then
  say "1. writing-app-password exists"
else
  say "1. creating writing-app-password"
  python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')" \
    | gcloud secrets create writing-app-password --replication-policy=automatic \
        --data-file=- --project "$PROJECT"
fi

# ---- 2. The roles, as the admin, with the password from step 1.
if [[ "$(as_migrator -Atc "select 1 from pg_roles where rolname = 'writing_app'")" == 1 ]]; then
  say "2. roles exist"
else
  say "2. creating writing_app and writing_bridge"
  sed "s/CHANGE_ME_writing_app/$(secret writing-app-password)/" backend/sql/01_writing_roles.sql \
    | as_admin
fi

# ---- 3. Migrate: 0041 (row-level security) and 0042 (schema and grants).
cd backend
say "3. alembic upgrade head"
alembic upgrade head 1>&2
alembic current

# ---- 4. Prove it on this database. One transaction, rolled back; any failed check stops here.
say "4. smoke test"
as_migrator -f sql/30_writing_rls_smoketest.sql 2>&1 | grep -E "NOTICE|ERROR|FAILED"

# ---- 5. Put you on the fixture class, or the console is a 403 for everyone — correctly.
say "5. grant $EMAIL on $SECTION"
python3 -m writing.roster.grant_staff --email "$EMAIL" --section "$SECTION"
cd ..

# ---- 6. Deploy: the routine, code-only redeploy (DEPLOY.md), then say what is SERVING.
say "6. deploy"
BEFORE=$(gcloud run services describe sip-api --region "$REGION" --format='value(status.latestReadyRevisionName)')
gcloud run deploy sip-api --source . --region "$REGION" \
  --update-env-vars GIT_SHA=$(git rev-parse HEAD)
TRAFFIC=$(gcloud run services describe sip-api --region "$REGION" --format='value(status.traffic)')
AFTER=$(gcloud run services describe sip-api --region "$REGION" --format='value(status.latestReadyRevisionName)')
echo "revision: $BEFORE -> $AFTER    traffic: $TRAFFIC"
[[ "$BEFORE" != "$AFTER" && "$TRAFFIC" == *"latestRevision': True"* ]] \
  || { echo "the new revision is not serving — see DEPLOY.md, '\"Done.\" is not a deployment'"; exit 1; }

# ---- 7. The corpus-scoring job: the new image, and the module path the move changed.
say "7. sip-score-corpus"
IMAGE=$(gcloud run services describe sip-api --region "$REGION" \
  --format='value(spec.template.spec.containers[0].image)')
ARGS=$(gcloud run jobs describe sip-score-corpus --region "$REGION" \
  --format='value(spec.template.spec.template.spec.containers[0].args)' | tr ';' ',' \
  | sed -E 's/(^|,)scoring\.run_scoring/\1writing.scoring.run_scoring/')
echo "args: $ARGS"
gcloud run jobs update sip-score-corpus --region "$REGION" --image "$IMAGE" --args="$ARGS"

say "done — open https://sip.prevagroup.com and go to Student work"
