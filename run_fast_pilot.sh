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
HN_TOPIC_REGEX="${HN_TOPIC_REGEX:-}"
HN_REWRITE_MODE="${HN_REWRITE_MODE:-none}"

# Optional Wikipedia Talk seeding (raw wikitext).
SEED_WIKI_TALK="${SEED_WIKI_TALK:-0}"
WIKI_PAGES="${WIKI_PAGES:-60}"
WIKI_LANG="${WIKI_LANG:-en}"
WIKI_MAX_CHARS="${WIKI_MAX_CHARS:-0}"
WIKI_THROTTLE_MS="${WIKI_THROTTLE_MS:-0}"

# Optional continuous HN refresh during daemon runtime.
export DCLAW_HN_REFRESH_SECONDS="${DCLAW_HN_REFRESH_SECONDS:-0}"
export DCLAW_HN_REFRESH_EACH_VIRTUAL_DAY="${DCLAW_HN_REFRESH_EACH_VIRTUAL_DAY:-false}"
export DCLAW_HN_REFRESH_STORIES="${DCLAW_HN_REFRESH_STORIES:-40}"
export DCLAW_HN_REFRESH_COMMENTS="${DCLAW_HN_REFRESH_COMMENTS:-120}"
export DCLAW_HN_TOPIC_REGEX="${DCLAW_HN_TOPIC_REGEX:-$HN_TOPIC_REGEX}"
export DCLAW_HN_REWRITE_MODE="${DCLAW_HN_REWRITE_MODE:-$HN_REWRITE_MODE}"
export DCLAW_HN_MAX_CHARS="${DCLAW_HN_MAX_CHARS:-500}"

# Optional continuous Wikipedia Talk refresh during daemon runtime.
export DCLAW_WIKI_REFRESH_SECONDS="${DCLAW_WIKI_REFRESH_SECONDS:-0}"
export DCLAW_WIKI_REFRESH_EACH_VIRTUAL_DAY="${DCLAW_WIKI_REFRESH_EACH_VIRTUAL_DAY:-false}"
export DCLAW_WIKI_REFRESH_PAGES="${DCLAW_WIKI_REFRESH_PAGES:-30}"
export DCLAW_WIKI_LANG="${DCLAW_WIKI_LANG:-$WIKI_LANG}"
export DCLAW_WIKI_MAX_CHARS="${DCLAW_WIKI_MAX_CHARS:-$WIKI_MAX_CHARS}"
export DCLAW_WIKI_THROTTLE_MS="${DCLAW_WIKI_THROTTLE_MS:-$WIKI_THROTTLE_MS}"

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
export DCLAW_CRITIC_STRICTNESS="${DCLAW_CRITIC_STRICTNESS:-1.0}"
export DCLAW_DIVERSITY_WINDOW="${DCLAW_DIVERSITY_WINDOW:-30}"
export DCLAW_DIVERSITY_MIN_SIM="${DCLAW_DIVERSITY_MIN_SIM:-0.55}"
export DCLAW_DIVERSITY_PENALTY_WEIGHT="${DCLAW_DIVERSITY_PENALTY_WEIGHT:-0.2}"

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
  echo "DCLAW_CRITIC_STRICTNESS=$DCLAW_CRITIC_STRICTNESS"
  echo "DCLAW_DIVERSITY_WINDOW=$DCLAW_DIVERSITY_WINDOW"
  echo "DCLAW_DIVERSITY_MIN_SIM=$DCLAW_DIVERSITY_MIN_SIM"
  echo "DCLAW_DIVERSITY_PENALTY_WEIGHT=$DCLAW_DIVERSITY_PENALTY_WEIGHT"
  echo "DCLAW_HN_REFRESH_SECONDS=$DCLAW_HN_REFRESH_SECONDS"
  echo "DCLAW_HN_REFRESH_EACH_VIRTUAL_DAY=$DCLAW_HN_REFRESH_EACH_VIRTUAL_DAY"
  echo "DCLAW_HN_REFRESH_STORIES=$DCLAW_HN_REFRESH_STORIES"
  echo "DCLAW_HN_REFRESH_COMMENTS=$DCLAW_HN_REFRESH_COMMENTS"
  echo "DCLAW_HN_TOPIC_REGEX=$DCLAW_HN_TOPIC_REGEX"
  echo "DCLAW_HN_REWRITE_MODE=$DCLAW_HN_REWRITE_MODE"
  echo "DCLAW_HN_MAX_CHARS=$DCLAW_HN_MAX_CHARS"
  echo "DCLAW_WIKI_REFRESH_SECONDS=$DCLAW_WIKI_REFRESH_SECONDS"
  echo "DCLAW_WIKI_REFRESH_EACH_VIRTUAL_DAY=$DCLAW_WIKI_REFRESH_EACH_VIRTUAL_DAY"
  echo "DCLAW_WIKI_REFRESH_PAGES=$DCLAW_WIKI_REFRESH_PAGES"
  echo "DCLAW_WIKI_LANG=$DCLAW_WIKI_LANG"
  echo "DCLAW_WIKI_MAX_CHARS=$DCLAW_WIKI_MAX_CHARS"
  echo "DCLAW_WIKI_THROTTLE_MS=$DCLAW_WIKI_THROTTLE_MS"
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
    --comments "$HN_COMMENTS" \
    --max-chars "$DCLAW_HN_MAX_CHARS" \
    ${HN_TOPIC_REGEX:+--topic-regex "$HN_TOPIC_REGEX"} \
    --rewrite-mode "$HN_REWRITE_MODE"
  echo
fi

if [[ "$SEED_WIKI_TALK" == "1" ]]; then
  echo "[dclaw] seeding Wikipedia Talk: pages=$WIKI_PAGES lang=$WIKI_LANG"
  "$PYTHON" "$ROOT_DIR/scripts/seed_wiki_talk_sqlite.py" \
    --db "$DCLAW_COMMUNITY_DB_PATH" \
    --pages "$WIKI_PAGES" \
    --lang "$WIKI_LANG" \
    --max-chars "$WIKI_MAX_CHARS" \
    --throttle-ms "$WIKI_THROTTLE_MS"
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
