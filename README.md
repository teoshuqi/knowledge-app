# Knowledge & Discovery Tool

A personal, single-user AI Engineering content aggregator: ingests RSS/Reddit/arXiv/GitHub-Trending
sources, detects cross-source trending stories, discovers topics over time, learns preferences, and
serves a daily Telegram digest plus a web dashboard.

**Design docs (read in this order):**

1. [`requirements-and-product-brief.md`](requirements-and-product-brief.md) — what this is and why (product/requirements)
2. [`phase1-technical-design.md`](phase1-technical-design.md) — high-level architecture, tooling decisions, DS methodology
3. [`low-level-design.md`](low-level-design.md) — exact schemas, interfaces, folder structure
4. [`implementation-plan.md`](implementation-plan.md) — the ticket-by-ticket build order this repo follows

This README covers only what's actually built and how to run the checks — not the *why*, which lives
in the docs above.

---

## What's implemented

**Phase 0 — Foundation** (tickets F-01–F-06 in `implementation-plan.md`):

| Ticket | What | Where |
|---|---|---|
| F-01 | Repo scaffold | `pyproject.toml`, `.env.example`, `.gitignore` |
| F-02 | Schema migration | `sql/migrations/001_initial_schema.sql` — bronze/silver/gold tables, `pipeline_config`, `pipeline_watermarks`. Apply with `scripts/migrate.sh` |
| F-03 | Docker Compose skeleton | `docker-compose.yml`, `Dockerfile` — postgres, prefect-server, prefect-worker |
| F-04 | Config loader | `src/config.py` — `pydantic-settings`, one `Settings` object for Postgres/Telegram/LLM/llama-server config |
| F-05 | Embedding model gate | `scripts/validate_embedding_model.py` — hand-labeled domain pairs decide the default embedding model (currently `sentence-transformers/all-MiniLM-L6-v2`; `bge-small-en-v1.5` was tried and rejected — see the script's own output) |
| F-06 | Local LLM throughput gate | `scripts/benchmark_llama_server.py` — checks a local `llama-server` clears the <5s per-item SLA before it's used instead of the Anthropic API |

Also present but **not yet reconciled with the finalized low-level design** (pre-dates the schema
fixes; see `src/pipeline/tasks.py` — two known mypy/pytype failures, tracked as a later pass, not
hidden): `src/connectors/`, `src/ml/`, `src/pipeline/`, `src/gold/repository.py`, `flows/flows.py`.
Everything from Phase 1 onward in `implementation-plan.md` is not yet built.

### Setup

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # fill in real values before running anything against Postgres/Telegram/an LLM
```

Applying the schema (once Postgres is up, e.g. via `docker compose up postgres`):

```bash
POSTGRES_DSN=postgresql://knowledge:knowledge@localhost:5432/knowledge scripts/migrate.sh
```

---

## CI gates

`scripts/ci_check.sh` runs every check below in one pass. Every tool in it was run for real against
this repo's actual files before being wired in — none of it is config written on faith, and where a
tool's default behavior actively fought this project's conventions (not just differed in style), that's
called out below, not silently overridden.

```bash
scripts/ci_check.sh          # full run
scripts/ci_check.sh --fast   # skips pytype and the cProfile run — for quick local iteration
```

Exit code is non-zero if any **hard gate** fails. **Soft checks** always run and never affect the exit
code — they report a number or produce an artifact for a human to read.

### Hard gates (block the build)

| Tool | Checks | Notes |
|---|---|---|
| `black --check` | Python formatting | |
| `ruff check` | Python lint | |
| `mypy` | Python types | |
| `pytype` | Python types (flow-sensitive) | Overlaps mypy, kept anyway — its None-narrowing caught a real bug (unguarded use of a `CanonicalDraft \| None`) mypy's config missed. `import-error` disabled: dependencies are added phase-by-phase, so a later phase's code legitimately imports a package not installed yet |
| `bandit` | Python security | `B101` (assert-used) skipped — this codebase's own convention is assert-based self-checks in scripts/gates, not a real security concern |
| `xenon` | Cyclomatic complexity budget | Gates at max grade B per function, A on average. `radon` itself has no pass/fail threshold — xenon is its own CI-gating companion tool |
| `pip-audit` | Dependency CVEs | |
| `tach check` | Module-dependency boundaries | Encodes tech design §1.3's SRP table and LLD §0/§3.1's "one query layer, two thin clients" rule in `tach.toml`. Verified as a real gate: a deliberate `connectors → gold` import was introduced, confirmed caught, then reverted |
| `pytest` (+ coverage report) | Tests | No `--cov-fail-under` yet — current coverage is a starting number, not yet meaningful enough to gate on |
| `shellcheck` | Bash correctness | |
| `shfmt --diff` | Bash formatting | 4-space indent (matches this repo's Python convention, not shfmt's tab default) |
| `sqlfluff lint` | SQL lint | `dialect=postgres` for now — revisit to `dbt`'s templater once `dbt/` exists (Phase 4) and `.sql` files are Jinja-templated. Config excludes `LT01`/`LT02`/`LT05`/`RF04` in `pyproject.toml` — see below |
| `yamllint` | YAML lint | `line-length` raised to 120 in `.yamllint` — 80 is unrealistic for compose files |

**sqlfluff exclusions, explained**: its default `fix` was tried and rejected after diffing the actual
output — it collapses the migration file's deliberate column alignment *and* relocates trailing inline
comments onto the wrong column (a comment about `embedding` ends up read as if it's about
`key_entities`). That's a real regression, not a style nit. `RF04` flags `key`/`value`/`action`/`summary`
as keyword-like identifiers — real column names already used across every design doc; renaming them is
out of scope for a portability concern this Postgres-only project doesn't have.

### Soft checks (informational only)

| Tool | Reports |
|---|---|
| `radon cc` / `radon mi` | Full complexity/maintainability report (xenon above is the actual gate) |
| `interrogate` | Docstring coverage — deliberately non-blocking; this project's style is sparse, WHY-only docstrings, not blanket coverage |
| `vulture` | Dead code — expect false positives on interface-stub parameters (`GoldRepository`'s methods, BERTopic's `BaseRepresentation` override); read before deleting anything it flags |
| `pyreverse` | UML class diagram → `.ci-artifacts/classes.dot`, `packages.dot` |
| `cProfile` | Test-suite profile → `.ci-artifacts/pytest.prof` (open with `python -m pstats`) |

### Evaluated and explicitly not added

- **cohesion** (LCOM-style class cohesion metric) — run directly against `src/` before deciding. Every
  Pydantic model scores 0% (the metric has nothing to measure on declarative fields with no methods),
  and `GoldRepository`'s interface-stub methods score 0% too — flagging exactly the "one deep interface
  over many entities" design the LLD calls out as intentional. For a Pydantic-model- and
  Protocol-heavy codebase like this one, the signal is inverted, not just noisy.

### Known, current failures

`mypy` and `pytype` both currently fail against `src/pipeline/tasks.py` — real, pre-existing bugs
(missing return statements; a `CanonicalDraft` used after a `None`-returning call without a guard) in a
draft file that predates the low-level design being finalized. Left alone deliberately: that file's
reconciliation with the current LLD is a separate, later pass, not silently patched here or hidden by
loosening the gate.
