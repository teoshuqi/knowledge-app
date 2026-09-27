# CI Check Enhancements

This document describes the three new code quality tools integrated into `scripts/ci_check.sh`.

## Installation

Install development dependencies with the new tools:

```bash
pip install -e ".[dev]"
```

Or install just the new tools:

```bash
pip install pydeps dot-layered-transform skylos
```

### System Requirements

- **pydeps + dot-layered-transform**: Requires Graphviz to be installed
  ```bash
  # macOS
  brew install graphviz
  
  # Ubuntu/Debian
  sudo apt-get install graphviz
  
  # Fedora/RHEL
  sudo dnf install graphviz
  ```

---

## Tool Overview

### 1. pydeps — Dependency Graph Visualization

**What it does**: Analyzes Python import statements and generates visual dependency graphs showing relationships between modules.

**Why add it**: 
- Visualize your module architecture
- Identify circular dependencies
- Understand import chains at a glance

**Output**: 
- `.svg` file in `.ci-artifacts/dependencies.svg`
- Shows all imports in your target package
- Circular dependencies highlighted in blue

**Key Features**:
- Bytecode-based analysis (finds actual runtime imports)
- Color-coded circular dependencies
- Configurable depth (max-bacon = hops away)

**Configuration** (in `pyproject.toml`):
```toml
[tool.pydeps]
exclude = ["tests", ".venv"]
max-bacon = 2  # Show only direct imports (2 hops)
rankdir = "TB"  # Top-to-bottom layout
```

**When to use**: 
- Reviewing module architecture
- Investigating import cycles
- Onboarding to the codebase

---

### 2. dot-layered-transform — Layered Architecture Analysis

**What it does**: Analyzes dependency graphs (DOT format) and transforms them into layered architecture diagrams with color-coded violations.

**Why add it**:
- Detect circular dependencies automatically
- Flag layer violations (e.g., domain importing from infrastructure)
- Enforce Clean Architecture or hexagonal patterns

**Output**:
- `.dot` file in `.ci-artifacts/layered.dot`
- Can be rendered to PNG/SVG with `dot` command
- Color-coded by architectural layer
- Edge colors indicate dependency type (owns/uses)

**Key Features**:
- Circular dependency detection
- Layer violation reporting
- Clean Architecture / DDD pattern support

**How it works**:
```
1. pydeps generates dependencies.dot
2. dot-layered-transform analyzes it for violations
3. Outputs layered.dot with color-coding and violations flagged
4. Render with: dot -Tpng .ci-artifacts/layered.dot -o .ci-artifacts/layered.png
```

**When to use**:
- Validating architecture boundaries
- Preventing dependency inversions
- Documenting architectural layers

---

### 3. skylos — Comprehensive Code Quality Scanning

**What it does**: Multi-language static analysis tool that detects dead code, security issues, hardcoded secrets, complexity violations, and AI-code defects.

**Why add it**:
- Finds hardcoded credentials (not caught by bandit)
- Detects dead code with framework awareness
- Scans dependencies for vulnerabilities
- Checks code complexity and nesting levels

**Output**:
- JSON format (suitable for parsing/CI integration)
- Summary in terminal with findings count
- Separate categories: secrets, dead code, quality, SCA

**Key Features**:
- **Secrets detection**: Finds hardcoded API keys, passwords, tokens
- **Dead code**: With framework awareness (FastAPI, Django, Flask routes are marked as live)
- **Quality metrics**: Complexity, nesting depth, cyclomatic complexity
- **SCA**: Scans dependencies for known vulnerabilities
- **Multi-language**: Also supports TypeScript, Go, Java, Rust, etc.

**Configuration** (in `pyproject.toml`):
```toml
[tool.skylos]
exclude = ["tests", ".venv", "docs", "__pycache__"]
quality = true      # Check complexity/nesting
secrets = true      # Detect hardcoded credentials
dead_code = true    # Find unused code
sca = true          # Scan dependencies
```

**Command-line options**:
- `-a, --audit`: Full audit (all checks)
- `--quality`: Complexity and nesting checks
- `--secrets`: Hardcoded credential detection
- `--trace`: Run tests to eliminate false positives
- `-o json`: Output as JSON

**When to use**:
- Security audits (secrets scanning)
- Code cleanup (dead code removal)
- Quality gate enforcement

---

## CI Integration Status

### Current Implementation

**As SOFT CHECKS** (informational, never block the build):
- ✅ pydeps — generates dependency graph
- ✅ dot-layered-transform — generates layered architecture diagram
- ✅ skylos — runs full quality audit

All three run with verbosity suppressed by default. Run with `--verbose` to see full output:

```bash
scripts/ci_check.sh --verbose
```

### Artifacts Generated

When the script runs, these files are created in `.ci-artifacts/`:

| File | Tool | Format | Usage |
|------|------|--------|-------|
| `dependencies.svg` | pydeps | SVG | View in browser; zoom to explore imports |
| `layered.dot` | dot-layered-transform | DOT | Raw graph format; render with `dot -Tpng` |
| `layered.png` | (manual render) | PNG | Generated from layered.dot with Graphviz |

---

## Troubleshooting

### "Graphviz not found"

pydeps and dot-layered-transform require Graphviz:
```bash
brew install graphviz  # macOS
sudo apt-get install graphviz  # Linux
```

### pydeps shows unexpected imports

pydeps uses bytecode analysis and may pick up dynamic imports. Common cases:
- Type checking imports (`if TYPE_CHECKING:`) are analyzed
- Lazy imports inside functions are found
- String-based imports may not be detected

Use `--exclude` in pyproject.toml to filter noise.

### skylos reports false positives on dead code

Use skylos's framework awareness by adding entrypoints to `pyproject.toml`:

```toml
[[tool.skylos.dead_code.entrypoints]]
type = "function"
name = ["create_app", "setup"]
reason = "framework entry point"
```

### "skylos: command not found" despite installation

Ensure the venv is activated:
```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Next Steps: Hard Gates vs Soft Checks

The current implementation treats all three as SOFT CHECKS. If you want to enforce architecture or quality rules:

**Option A: Circular Dependency Hard Gate**

Add to ci_check.sh to fail if circular dependencies found:
```bash
run "dot-layered-transform (no circular deps allowed)" \
    -- bash -c "python -m dot_analyzer.cli analyze $ARTIFACTS/dependencies.dot | grep -q 'cycle' && exit 1 || exit 0"
```

**Option B: Secrets/Security Hard Gate**

Add to ci_check.sh to fail if secrets detected:
```bash
run "skylos (no hardcoded secrets)" \
    -- "$BIN/skylos" . --secrets --exclude tests
```

**Option C: Dead Code Hard Gate**

Add to ci_check.sh to fail if dead code above threshold:
```bash
run "skylos (dead code audit)" \
    -- "$BIN/skylos" . --dead_code --exclude tests
```

---

## References

- [pydeps Documentation](https://github.com/thebjorn/pydeps)
- [dot-layered-transform Repository](https://github.com/J4CKVVH173/dot-layered-transform)
- [skylos Documentation](https://docs.skylos.dev/)
- [Tool Research Details](tools_research.md)
