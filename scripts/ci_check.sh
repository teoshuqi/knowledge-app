#!/usr/bin/env bash
# CI check runner: format, lint, type-check, security scan, test, and audit code quality.
#
# Two tiers: HARD gates block the build (exit 1 on failure); SOFT checks report metrics/artifacts.
# Covers: Python, bash, SQL, YAML, architecture, and dependencies.
#
# Usage: scripts/ci_check.sh [--fast] [--verbose]
#   --fast     skip slow checks (pytype, cProfile)
#   --verbose  show full tool output
#
# HARD GATES (build-blocking):
#   Format: black (Python), shfmt (bash), sqlfluff (SQL), yamllint (YAML)
#   Lint: ruff (Python linter), shellcheck (bash linter)
#   Type: mypy, pytype (static type checking)
#   Security: bandit (code security), pip-audit (dependency vulnerabilities)
#   Architecture: tach (module boundaries)
#   Complexity: xenon (cyclomatic complexity budget)
#   Test: pytest (unit tests + coverage)
#
# SOFT CHECKS (informational, never fail):
#   Metrics: radon (complexity report), interrogate (docstring %), vulture (dead code)
#   Architecture: pydeps (dependency graph), dot-layered-transform (layered diagram)
#   Audit: skylos (secrets, dead code, quality issues)
#   Visualization: pyreverse (UML diagram)
#   Profile: cProfile (test performance)

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

BIN="${CI_PYTHON_BIN:-.venv/bin}"
TARGETS=(src scripts)
ARTIFACTS=".ci-artifacts"
FAST=0
VERBOSE=0
[[ "${1:-}" == "--fast" ]] && FAST=1
[[ "${1:-}" == "--verbose" ]] && VERBOSE=1
[[ "${2:-}" == "--fast" ]] && FAST=1
[[ "${2:-}" == "--verbose" ]] && VERBOSE=1

mkdir -p "$ARTIFACTS"

# Temp storage for results
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

GATE_PASS=0
GATE_FAIL=0
FAILED_NAMES=()
GATE_INDEX=0

# run NAME -- <command...>
run() {
    local name="$1"
    shift
    [[ "$1" == "--" ]] && shift

    ((GATE_INDEX++))
    local output_file="$TEMP_DIR/gate_$GATE_INDEX.out"

    if "$@" >"$output_file" 2>&1; then
        ((GATE_PASS++))
        echo "✅ $name"
    else
        ((GATE_FAIL++))
        FAILED_NAMES+=("$name|$output_file")
        echo "❌ $name"
    fi
}

# soft NAME -- <command...>
soft() {
    local name="$1"
    shift
    [[ "$1" == "--" ]] && shift
    "$@" >/dev/null 2>&1 || true
}

# ================================================================ HARD GATES

run "black --check" -- "$BIN/black" --check --target-version py312 "${TARGETS[@]}" tests
run "ruff check" -- "$BIN/ruff" check "${TARGETS[@]}" tests
run "mypy" -- "$BIN/mypy" "${TARGETS[@]}"
run "bandit" -- "$BIN/bandit" -c pyproject.toml -r "${TARGETS[@]}" -q
run "xenon (complexity budget: max B per function, A on average)" \
    -- "$BIN/xenon" --max-absolute B --max-modules A --max-average A "${TARGETS[@]}"
run "pip-audit" -- "$BIN/pip-audit"
run "tach check (module boundaries — tech design §1.3, LLD §0/§3.1)" \
    -- "$BIN/tach" check
run "pytest" -- "$BIN/pytest" --cov=src --cov-report=term-missing -q

# --- non-Python files: bash, SQL, YAML ---
run "shellcheck" -- "$BIN/shellcheck" scripts/*.sh
run "shfmt --diff (4-space indent, matching this repo's Python convention)" \
    -- "$BIN/shfmt" -i 4 -d scripts/*.sh
run "sqlfluff lint (config: pyproject.toml [tool.sqlfluff.core])" \
    -- "$BIN/sqlfluff" lint sql/
run "yamllint" -- "$BIN/yamllint" docker-compose.yml

if [[ $FAST -eq 0 ]]; then
    # pytype overlaps mypy but catches different things (flow-sensitive
    # None-narrowing in particular) — see the ci notes in the repo's
    # commit history for a concrete example this caught that mypy didn't.
    # import-error is disabled: this project adds dependencies phase by
    # phase (pyproject.toml's own convention), so code for a later phase
    # legitimately imports a package not installed yet.
    run "pytype" -- "$BIN/pytype" -d import-error -k "${TARGETS[@]}"
fi

# ================================================================ SOFT CHECKS

soft "radon cc (full report; xenon above is the actual gate)" \
    -- "$BIN/radon" cc "${TARGETS[@]}" -a
soft "radon mi (maintainability index)" \
    -- "$BIN/radon" mi "${TARGETS[@]}"
soft "interrogate (docstring coverage — informational; this codebase's own convention is sparse, WHY-only docstrings, not blanket coverage)" \
    -- "$BIN/interrogate" -v "${TARGETS[@]}"
soft "vulture (dead code — expect false positives on interface stub params, e.g. GoldRepository's method signatures and BERTopic's BaseRepresentation override; read before deleting anything it flags)" \
    -- "$BIN/vulture" "${TARGETS[@]}" --min-confidence 80

soft "pyreverse (UML class diagram -> $ARTIFACTS/classes.dot, packages.dot)" \
    -- bash -c "$BIN/pyreverse -o dot -d '$ARTIFACTS' \$(find ${TARGETS[*]} -name '*.py')"

soft "pydeps (dependency graph -> $ARTIFACTS/dependencies.svg)" \
    -- "$BIN/pydeps" "${TARGETS[0]}" -o "$ARTIFACTS/dependencies" --noshow

soft "dot-layered-transform (layered architecture -> $ARTIFACTS/layered.dot)" \
    -- bash -c "$BIN/python -m dot_analyzer.cli transform $ARTIFACTS/dependencies.dot -o $ARTIFACTS/layered.dot 2>/dev/null || true"

soft "skylos (secrets, quality, dead code audit)" \
    -- "$BIN/skylos" . -a --exclude tests

if [[ $FAST -eq 0 ]]; then
    soft "cProfile (test-suite profile -> $ARTIFACTS/pytest.prof; open with 'python -m pstats')" \
        -- "$BIN/python" -m cProfile -o "$ARTIFACTS/pytest.prof" -m pytest -q
fi

# ================================================================ RESULT

echo ""
printf "╔════════════════════════════════════════════════════════════════════╗\n"
if [[ $GATE_FAIL -eq 0 ]]; then
    printf "║ BUILD STATUS: ✅ PASSED (all hard gates)                           ║\n"
else
    printf "║ BUILD STATUS: ❌ FAILED (exit code 1)                              ║\n"
fi
printf "╚════════════════════════════════════════════════════════════════════╝\n"
echo ""

echo "HARD GATES: $((GATE_PASS + GATE_FAIL)) total ($GATE_PASS PASS, $GATE_FAIL FAIL)"
echo ""

# Show error details if any failures
if [[ $GATE_FAIL -gt 0 ]]; then
    echo "═══════════════════════════════════════════════════════════════════"
    echo "ERROR DETAILS"
    echo "═══════════════════════════════════════════════════════════════════"
    echo ""

    for entry in "${FAILED_NAMES[@]}"; do
        name="${entry%|*}"
        output_file="${entry#*|}"
        echo "[$name]"

        # Extract key error lines (filter noise)
        if [[ "$name" == *"mypy"* ]] || [[ "$name" == *"pytype"* ]]; then
            grep -E "^\s*(src/|error:|Found|FAILED:|ERROR)" "$output_file" 2>/dev/null | head -20 || true
        elif [[ "$name" == *"pytest"* ]]; then
            grep -E "(FAILED|ERROR|AssertionError|test_)" "$output_file" 2>/dev/null | head -15 || true
        else
            head -15 "$output_file" 2>/dev/null || true
        fi

        # Count lines and indicate if truncated
        line_count=$(wc -l <"$output_file" 2>/dev/null || echo 0)
        if [[ $line_count -gt 20 ]]; then
            echo "  ... (showing first 20 lines of $line_count)"
        fi
        echo ""
    done

    # Quick fix suggestions
    failed_names_str="${FAILED_NAMES[*]}"
    if [[ "$failed_names_str" == *"mypy"* ]] || [[ "$failed_names_str" == *"pytype"* ]]; then
        echo "QUICK FIX:"
        echo "  • src/pipeline/tasks.py:224–225 — add return statements to _simhash, _enrichment_prompt"
        echo "  • src/pipeline/tasks.py:101+ — guard draft against None after to_canonical_draft()"
        echo ""
    fi
fi

echo "═══════════════════════════════════════════════════════════════════"
echo "SOFT CHECKS: completed"
echo "  (docstring coverage, complexity, dead code, UML, architecture,"
echo "   dependencies, layered design, quality audit, profiling)"
if [[ $VERBOSE -eq 1 ]]; then
    echo ""
    echo "Full output available in: $ARTIFACTS/"
else
    echo "  Run with --verbose to see full output"
fi
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# Exit with proper code
if [[ $GATE_FAIL -eq 0 ]]; then
    exit 0
else
    exit 1
fi
