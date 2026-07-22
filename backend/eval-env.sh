# Eval-runner session env for Cloud Shell.  SOURCE this, don't run it:
#     source backend/eval-env.sh
#
# Sets everything `evals.run_evals` needs in the current shell. The password is NOT in this file
# — it's pulled from Secret Manager (secret: eval-runner-password), so nothing secret is committed
# or typed. Then start the Cloud SQL proxy in another tab (printed below).
#
# Everything exported here except the password is non-secret: the eval account email, the service
# URL, the traces bucket, and the Identity Platform Web API key (already public + committed in
# frontend/src/firebase.ts).

export EVAL_PRINCIPAL_EMAIL=eval-runner@prevagroup.com
export EVAL_TARGET_URL=https://sip-api-1013838667941.us-central1.run.app
export TRACES_BUCKET=school-improvement-traces
export IDENTITY_PLATFORM_API_KEY=$(grep -oE 'AIza[0-9A-Za-z_-]+' \
  "$(git rev-parse --show-toplevel)/frontend/src/firebase.ts" | head -1)
export EVAL_PRINCIPAL_PASSWORD=$(gcloud secrets versions access latest \
  --secret=eval-runner-password 2>/dev/null)

if [ -z "$EVAL_PRINCIPAL_PASSWORD" ]; then
  echo "⚠  couldn't read eval-runner-password from Secret Manager."
  echo "   Create it once:  printf '%s' 'THE-PASSWORD' | gcloud secrets create eval-runner-password --data-file=-"
else
  echo "✓  eval env set (password from Secret Manager)."
fi
echo "→  start the proxy in another tab:"
echo "   cloud-sql-proxy school-improvement-501916:us-central1:school-improvement-sql --port 5432"
