#!/usr/bin/env bash
#
# One entry point for the whole automated suite.
#
#   scripts/run-tests.sh              unit + API + acceptance + frontend unit
#   scripts/run-tests.sh --all        the above, then the live deployment suites
#   scripts/run-tests.sh --e2e        only the live deployment suites
#   scripts/run-tests.sh --coverage   with coverage reports
#
# The default layers need no infrastructure. The live layers need a running
# deployment; start one with `docker compose up -d && docker compose run --rm seed`.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
BASE_URL="${AIT_E2E_BASE_URL:-http://localhost:8080}"

RUN_DEFAULT=1
RUN_E2E=0
COVERAGE=0

for argument in "$@"; do
  case "$argument" in
    --all) RUN_E2E=1 ;;
    --e2e) RUN_E2E=1; RUN_DEFAULT=0 ;;
    --coverage) COVERAGE=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $argument" >&2; exit 2 ;;
  esac
done

if [ -x "$BACKEND/.venv/Scripts/python.exe" ]; then
  PYTHON="$BACKEND/.venv/Scripts/python.exe"      # Windows virtual environment
elif [ -x "$BACKEND/.venv/bin/python" ]; then
  PYTHON="$BACKEND/.venv/bin/python"
else
  PYTHON="python"
fi

FAILURES=()
declare -A RESULTS=()

run() {
  local name="$1"; shift
  echo ""
  echo "── $name ──────────────────────────────────────────────"
  local started=$SECONDS
  if "$@"; then
    RESULTS["$name"]="pass $(( SECONDS - started ))s"
  else
    RESULTS["$name"]="FAIL $(( SECONDS - started ))s"
    FAILURES+=("$name")
  fi
}

backend_pytest() {
  local marker_args=()
  if [ "$COVERAGE" = "1" ]; then
    marker_args=(--cov=app --cov-report=term-missing --cov-report=html:htmlcov)
  fi
  (cd "$BACKEND" && "$PYTHON" -m pytest "$@" "${marker_args[@]}")
}

deployment_is_up() {
  curl -fsS --max-time 5 "$BASE_URL/health" >/dev/null 2>&1
}

if [ "$RUN_DEFAULT" = "1" ]; then
  run "backend unit (service level)"      backend_pytest tests/unit -q
  run "backend API (functional)"          backend_pytest tests/api -q
  run "acceptance scenarios AT-01..AT-20" backend_pytest tests/acceptance -q
  run "frontend unit and component"       bash -c "cd '$FRONTEND' && npx vitest run"
  run "frontend type check"               bash -c "cd '$FRONTEND' && npx tsc --noEmit"
fi

if [ "$RUN_E2E" = "1" ]; then
  if deployment_is_up; then
    run "live API end to end" \
      bash -c "cd '$BACKEND' && AIT_E2E_BASE_URL='$BASE_URL' '$PYTHON' -m pytest tests/e2e -q"
    run "browser end to end" \
      bash -c "cd '$FRONTEND' && AIT_E2E_BASE_URL='$BASE_URL' npx playwright test"
  else
    echo ""
    echo "!! No deployment answering at $BASE_URL — skipping the live suites."
    echo "   Start one with: docker compose up -d && docker compose run --rm seed"
    RESULTS["live suites"]="skipped (no deployment at $BASE_URL)"
  fi
fi

echo ""
echo "══ summary ═══════════════════════════════════════════════"
for name in "${!RESULTS[@]}"; do
  printf '  %-40s %s\n' "$name" "${RESULTS[$name]}"
done

if [ ${#FAILURES[@]} -gt 0 ]; then
  echo ""
  echo "FAILED: ${FAILURES[*]}"
  exit 1
fi
echo ""
echo "All selected suites passed."
