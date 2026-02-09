#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-$ROOT_DIR/venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing venv python at: $PYTHON" >&2
  echo "Create venv first, then rerun." >&2
  exit 1
fi

# --- Fast pilot defaults (override via env vars) ---
# Target: quick end-to-end run with OpenAI API + very fast virtual-day.
DURATION_SECONDS="${DURATION_SECONDS:-600}"
RUN_ID="${RUN_ID:-pilot_fast_$(date -u +%Y%m%dT%H%M%SZ)}"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/artifacts/$RUN_ID}"

SEED_HN="${SEED_HN:-1}"
HN_STORIES="${HN_STORIES:-60}"
HN_COMMENTS="${HN_COMMENTS:-200}"

export DCLAW_COMMUNITY_DB_PATH="${DCLAW_COMMUNITY_DB_PATH:-community.db}"
export DCLAW_COMMUNITY_TZ="${DCLAW_COMMUNITY_TZ:-America/Los_Angeles}"
export DCLAW_AI_POPULATION="${DCLAW_AI_POPULATION:-20}"
export DCLAW_AI_TICK_SECONDS="${DCLAW_AI_TICK_SECONDS:-30}"

# Virtual-day compression.
# Requested: 2 minutes per virtual day (120s).
export DCLAW_VIRTUAL_DAY_SECONDS="${DCLAW_VIRTUAL_DAY_SECONDS:-120}"

# Main model via OpenAI API.
export DCLAW_COMMUNITY_PROVIDER="${DCLAW_COMMUNITY_PROVIDER:-openai}"
export DCLAW_COMMUNITY_MODEL="${DCLAW_COMMUNITY_MODEL:-gpt-4o-mini}"
export DCLAW_COMMUNITY_TIMEOUT_SECONDS="${DCLAW_COMMUNITY_TIMEOUT_SECONDS:-30}"
export DCLAW_COMMUNITY_ALLOW_FALLBACK="${DCLAW_COMMUNITY_ALLOW_FALLBACK:-false}"

# Enable rumination (反刍) by default for this protocol.
export DCLAW_RUMINATION_ENABLED="${DCLAW_RUMINATION_ENABLED:-true}"
export DCLAW_RUMINATION_PROVIDER="${DCLAW_RUMINATION_PROVIDER:-openai}"
export DCLAW_RUMINATION_MODEL="${DCLAW_RUMINATION_MODEL:-gpt-4o-mini}"
export DCLAW_RUMINATION_LLM_BUDGET="${DCLAW_RUMINATION_LLM_BUDGET:-1}"
export DCLAW_EMOTION_INERTIA="${DCLAW_EMOTION_INERTIA:-0.05}"

export PYTHONPATH="$ROOT_DIR"

# Optional local secrets (not committed). Put OPENAI_API_KEY / OPENAI_BASE_URL here.
if [[ -f "$ROOT_DIR/secrets.env" ]]; then
  # shellcheck disable=SC1090
  source "$ROOT_DIR/secrets.env"
fi

# macOS ships Bash 3.2 by default; avoid Bash 4+ ${var,,} expansion.
provider_lower="$(printf '%s' "${DCLAW_COMMUNITY_PROVIDER:-}" | tr '[:upper:]' '[:lower:]')"
if [[ "$provider_lower" == "openai" ]]; then
  if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo "Missing OPENAI_API_KEY (required for DCLAW_COMMUNITY_PROVIDER=openai)." >&2
    echo "Optional: set OPENAI_BASE_URL to use a proxy; default is https://api.openai.com/v1" >&2
    exit 2
  fi
fi

mkdir -p "$OUT_DIR"
cd "$OUT_DIR"

echo "[dclaw] output dir: $OUT_DIR"
echo "[dclaw] duration seconds: $DURATION_SECONDS"
echo "[dclaw] provider/model: $DCLAW_COMMUNITY_PROVIDER/$DCLAW_COMMUNITY_MODEL"
echo "[dclaw] tick seconds: $DCLAW_AI_TICK_SECONDS"
echo "[dclaw] virtual day seconds: $DCLAW_VIRTUAL_DAY_SECONDS"
echo "[dclaw] rumination enabled: $DCLAW_RUMINATION_ENABLED"
echo

{
  echo "commit=$(cd "$ROOT_DIR" && git rev-parse HEAD)"
  echo "run_id=$RUN_ID"
  echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "duration_seconds=$DURATION_SECONDS"
  echo "DCLAW_COMMUNITY_TZ=$DCLAW_COMMUNITY_TZ"
  echo "DCLAW_AI_POPULATION=$DCLAW_AI_POPULATION"
  echo "DCLAW_AI_TICK_SECONDS=$DCLAW_AI_TICK_SECONDS"
  echo "DCLAW_VIRTUAL_DAY_SECONDS=$DCLAW_VIRTUAL_DAY_SECONDS"
  echo "DCLAW_COMMUNITY_PROVIDER=$DCLAW_COMMUNITY_PROVIDER"
  echo "DCLAW_COMMUNITY_MODEL=$DCLAW_COMMUNITY_MODEL"
  echo "DCLAW_COMMUNITY_TIMEOUT_SECONDS=$DCLAW_COMMUNITY_TIMEOUT_SECONDS"
  echo "DCLAW_COMMUNITY_ALLOW_FALLBACK=$DCLAW_COMMUNITY_ALLOW_FALLBACK"
  echo "DCLAW_EMOTION_INERTIA=$DCLAW_EMOTION_INERTIA"
  echo "DCLAW_RUMINATION_ENABLED=$DCLAW_RUMINATION_ENABLED"
  echo "DCLAW_RUMINATION_PROVIDER=$DCLAW_RUMINATION_PROVIDER"
  echo "DCLAW_RUMINATION_MODEL=$DCLAW_RUMINATION_MODEL"
  echo "DCLAW_RUMINATION_LLM_BUDGET=$DCLAW_RUMINATION_LLM_BUDGET"
} > run_config.env

cleanup() {
  "$PYTHON" -m dclaw.main --mode community-daemon --daemon-action stop >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

if [[ "$SEED_HN" == "1" ]]; then
  echo "[dclaw] seeding real data (HN): stories=$HN_STORIES comments=$HN_COMMENTS"
  "$PYTHON" "$ROOT_DIR/scripts/seed_hn_sqlite.py" \
    --db "$DCLAW_COMMUNITY_DB_PATH" \
    --stories "$HN_STORIES" \
    --comments "$HN_COMMENTS"
  echo
fi

echo "[dclaw] starting daemon..."
"$PYTHON" -m dclaw.main --mode community-daemon --daemon-action start

echo "[dclaw] running... (Ctrl-C to stop early)"
end_ts=$((SECONDS + DURATION_SECONDS))
while (( SECONDS < end_ts )); do
  sleep 1
done

echo "[dclaw] stopping daemon..."
"$PYTHON" -m dclaw.main --mode community-daemon --daemon-action stop

echo
echo "[dclaw] done."
echo "[dclaw] telemetry: $OUT_DIR/experiment_telemetry.csv"
echo "[dclaw] log: $OUT_DIR/community_daemon.log"
echo "[dclaw] db: $OUT_DIR/$DCLAW_COMMUNITY_DB_PATH"
