#!/usr/bin/env bash
# sip_one_school.sh — extract (and optionally load) ONE school's SPSA, with preflight.
#
# The batch machinery (batch_extract: alias/level/crosswalk, detached nohup runs) exists
# for fanning out over a whole district. For a single school it's overkill and error-prone.
# This wraps the single-file path (extract_sip -> review -> load_plan_extractions) and,
# crucially, checks the things that otherwise fail cryptically MID-RUN — before spending
# an Anthropic token.
#
# Run from backend/ in Cloud Shell (where gcloud, ADC, and the Cloud SQL proxy live).
#
#   ./etl/ca/sip/sip_one_school.sh extract \
#       --district-id 0640980 --plan-year 2025-26 \
#       --context-file etl/ca/sip/contexts/vusd_spsa.txt \
#       --pdf gs://school-improvement-501916-raw/raw/ca/districts/0640980/sip/VenturaHigh.pdf \
#       --out ventura_high.json
#
#   # ...review ventura_high.json (flip metric links proposed->confirmed if using batch_load)...
#
#   ./etl/ca/sip/sip_one_school.sh load --out ventura_high.json           # -> plan_extraction (demo)
#   ./etl/ca/sip/sip_one_school.sh load --out ventura_high.json \         # -> plan_* (normalized, private)
#       --tenant vusd --display-name "Ventura Unified"
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }
note() { echo "[sip] $*" >&2; }

CMD="${1:-}"; shift || true
[[ "$CMD" == "extract" || "$CMD" == "load" || "$CMD" == "check" ]] \
  || die "usage: $0 {check|extract|load} [flags]  (see header)"

DISTRICT_ID=""; PLAN_YEAR=""; CONTEXT_FILE=""; PDF=""; OUT=""; TENANT=""; DISPLAY_NAME=""; EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --district-id)   DISTRICT_ID="$2"; shift 2 ;;
    --plan-year)     PLAN_YEAR="$2"; shift 2 ;;
    --context-file)  CONTEXT_FILE="$2"; shift 2 ;;
    --pdf)           PDF="$2"; shift 2 ;;
    --out)           OUT="$2"; shift 2 ;;
    --tenant)        TENANT="$2"; shift 2 ;;
    --display-name)  DISPLAY_NAME="$2"; shift 2 ;;
    *)               EXTRA+=("$1"); shift ;;   # passed through to the python module
  esac
done

# --- preflight: fail fast, with a fix, BEFORE any billed work ---------------
preflight_common() {
  command -v gcloud >/dev/null || die "gcloud not found — run this in Cloud Shell, not the local box."
  [[ -n "${GCP_PROJECT:-}" ]] || die "GCP_PROJECT not set — 'export GCP_PROJECT=school-improvement-501916'."
  gcloud auth application-default print-access-token >/dev/null 2>&1 \
    || die "no ADC token — run 'gcloud auth application-default login'."
  note "ok: gcloud, GCP_PROJECT=$GCP_PROJECT, ADC token present."
}

preflight_pdf() {
  [[ -n "$PDF" ]] || die "--pdf is required for extract."
  if [[ "$PDF" == gs://* ]]; then
    gcloud storage ls "$PDF" >/dev/null 2>&1 || die "cannot read PDF at $PDF (check the path/permissions)."
  else
    [[ -f "$PDF" ]] || die "local PDF not found: $PDF"
  fi
  [[ -z "$CONTEXT_FILE" || -f "$CONTEXT_FILE" ]] || die "context file not found: $CONTEXT_FILE"
  note "ok: PDF readable at $PDF"
}

case "$CMD" in
  check)
    preflight_common
    [[ -n "$PDF" ]] && preflight_pdf
    note "preflight passed."
    ;;

  extract)
    preflight_common; preflight_pdf
    [[ -n "$OUT" ]] || die "--out <file.json> is required."
    ctx=(); [[ -n "$CONTEXT_FILE" ]] && ctx=(--context-file "$CONTEXT_FILE")
    yr=();  [[ -n "$PLAN_YEAR" ]]    && yr=(--plan-year "$PLAN_YEAR")
    dist=(); [[ -n "$DISTRICT_ID" ]] && dist=(--district-id "$DISTRICT_ID")

    # The extractor reads + hashes + counts pages and enforces the size cap BEFORE the billed
    # API call, so it already fails fast on an unreadable/oversize PDF. No separate --dry-run
    # pass (which would re-download the whole PDF); use `check` for a no-spend plumbing test.
    note "extracting (reads the PDF once, then the billed API call)…"
    python -m etl.ca.sip.extract_sip "$PDF" "${dist[@]}" "${yr[@]}" "${ctx[@]}" \
      --out "$OUT" "${EXTRA[@]}"

    note "wrote $OUT — review it, then:"
    note "  $0 load --out $OUT                                  # -> plan_extraction (serves the demo)"
    note "  $0 load --out $OUT --tenant <t> --display-name '<D>'  # -> plan_* (normalized, private)"
    ;;

  load)
    preflight_common
    [[ -n "$OUT" && -f "$OUT" ]] || die "--out <file.json> must point at an extracted JSON."
    # in-prefix accepts a local dir; isolate the one file so the loader picks up only it.
    tmp="$(mktemp -d)"; cp "$OUT" "$tmp/"; note "loading from $tmp"
    if [[ -n "$TENANT" ]]; then
      [[ -n "$DISPLAY_NAME" ]] || die "--display-name required with --tenant (normalized load)."
      python -m etl.ca.sip.batch_load --tenant "$TENANT" --display-name "$DISPLAY_NAME" \
        --in-prefix "$tmp" --force "${EXTRA[@]}"
    else
      python -m etl.ca.sip.load_plan_extractions --in-prefix "$tmp" "${EXTRA[@]}"
    fi
    note "load done."
    ;;
esac
