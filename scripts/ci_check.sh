#!/usr/bin/env bash
# CI check runner. Two tiers:
#   HARD gates — a real failure blocks the build (correctness, security, style).
#   SOFT checks — always run, never fail the build; they report a number or
#     produce an artifact for a human to look at, and don't have a
#     principled pass/fail threshold at this project's current size.
#
# Every tool here was run for real against this repo before being wired in —
# none of this is a guess at what "should" work.
#
# Usage: scripts/ci_check.sh [--fast]
#   --fast  skip the two slowest checks (pytype, cProfile) — for local use
#           while iterating; CI itself always runs the full set.

set -uo pipefail
cd "$(dirname "$0")/.."

BIN="${CI_PYTHON_BIN:-.venv/bin}"
TARGETS="src scripts"
ARTIFACTS=".ci-artifacts"
FAST=0
[[ "${1:-}" == "--fast" ]] && FAST=1

mkdir -p "$ARTIFACTS"
FAILED=()

hr() { printf '%s\n' "----------------------------------------------------------------"; }

# run NAME -- <command...>
# Runs a HARD gate: on failure, records NAME and keeps going (so one broken
# check doesn't hide the rest of the report) — the script only exits
# non-zero at the very end, once everything has had a chance to run.
run() {
    local name="$1"; shift
    [[ "$1" == "--" ]] && shift
    hr
    echo "[$name]"
    if "$@"; then
        echo "PASS: $name"
    else
        echo "FAIL: $name"
        FAILED+=("$name")
    fi
}

# soft NAME -- <command...>
# Runs an informational check. Always reports PASS/DONE regardless of the
# command's own exit code — these produce a number or artifact, not a gate.
soft() {
    local name="$1"; shift
    [[ "$1" == "--" ]] && shift
    hr
    echo "[$name] (informational — does not affect exit code)"
    "$@" || true
}

# ---------------------------------------------------------------- HARD GATES

run "black --check" -- "$BIN/black" --check --target-version py312 $TARGETS tests
run "ruff check"    -- "$BIN/ruff" check $TARGETS tests
run "mypy"          -- "$BIN/mypy" $TARGETS
run "bandit"        -- "$BIN/bandit" -c pyproject.toml -r $TARGETS -q
run "xenon (complexity budget: max B per function, A on average)" \
    -- "$BIN/xenon" --max-absolute B --max-modules A --max-average A $TARGETS
run "pip-audit" -- "$BIN/pip-audit"
run "pytest"    -- "$BIN/pytest" --cov=src --cov-report=term-missing -q

if [[ $FAST -eq 0 ]]; then
    # pytype overlaps mypy but catches different things (flow-sensitive
    # None-narrowing in particular) — see the ci notes in the repo's
    # commit history for a concrete example this caught that mypy didn't.
    # import-error is disabled: this project adds dependencies phase by
    # phase (pyproject.toml's own convention), so code for a later phase
    # legitimately imports a package not installed yet.
    run "pytype" -- "$BIN/pytype" -d import-error -k $TARGETS
fi

# ---------------------------------------------------------------- SOFT CHECKS

soft "radon cc (full report; xenon above is the actual gate)" \
    -- "$BIN/radon" cc $TARGETS -a
soft "radon mi (maintainability index)" \
    -- "$BIN/radon" mi $TARGETS
soft "interrogate (docstring coverage — informational; this codebase's own convention is sparse, WHY-only docstrings, not blanket coverage)" \
    -- "$BIN/interrogate" -v $TARGETS
soft "vulture (dead code — expect false positives on interface stub params, e.g. GoldRepository's method signatures and BERTopic's BaseRepresentation override; read before deleting anything it flags)" \
    -- "$BIN/vulture" $TARGETS --min-confidence 80

soft "pyreverse (UML class diagram -> $ARTIFACTS/classes.dot, packages.dot)" \
    -- bash -c "$BIN/pyreverse -o dot -d '$ARTIFACTS' \$(find $TARGETS -name '*.py')"

if [[ $FAST -eq 0 ]]; then
    soft "cProfile (test-suite profile -> $ARTIFACTS/pytest.prof; open with 'python -m pstats')" \
        -- "$BIN/python" -m cProfile -o "$ARTIFACTS/pytest.prof" -m pytest -q
fi

# --------------------------------------------------------------------- RESULT

hr
if [[ ${#FAILED[@]} -eq 0 ]]; then
    echo "All hard gates passed."
    exit 0
else
    echo "Failed hard gates: ${FAILED[*]}"
    exit 1
fi
