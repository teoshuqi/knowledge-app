# Python Code Quality & Analysis Tools Research

Research conducted: 2026-09-27

This document provides detailed findings on four Python code quality and analysis tools, including their purpose, usage, output formats, and configuration options.

---

## 1. CodeGuardian

### Official Source

- **GitHub Repository**: [The-Swarm-Corporation/CodeGuardian](https://github.com/The-Swarm-Corporation/CodeGuardian)
- **License**: MIT License

### Purpose & Main Features

CodeGuardian is an AI-powered tool designed to automate the generation of unit tests for Python codebases. It leverages swarms of agents to generate, execute, and monitor tests while providing insights into code quality. [GitHub - CodeGuardian]

Key features include:

- **Automated test generation** for existing Python code
- **Test execution** with immediate result visibility
- **Real-time monitoring** of test performance
- **Code health reporting** with coverage and quality metrics
- **CI/CD integration** for seamless workflow incorporation
- **Customizable settings** tailored to project needs
[GitHub - CodeGuardian]

### How It's Used

Users install the package via pip, configure an AI model (like GPT-4), and instantiate a CodeGuardian object with target classes. The system then generates pytest-compatible tests, runs them, and delivers comprehensive reports on code reliability and maintainability. [GitHub - CodeGuardian]

Basic usage pattern:

```python
from code_guardian import CodeGuardian

# Instantiate with target classes
guardian = CodeGuardian(config=your_config)

# Generate and execute tests
results = guardian.generate_tests(target_classes)
```

### Output Format & Artifacts

- **Test files**: pytest-compatible Python test files
- **Reports**: Comprehensive code reliability and maintainability reports
- **Metrics**: Coverage and quality metrics
- **Health summaries**: Real-time code health dashboards

[GitHub - CodeGuardian]

### Configuration Options

Configuration is handled through a CodeGuardian object instantiation with customizable settings:

- AI model selection (e.g., GPT-4)
- Target class specification
- Project-specific settings and parameters
- Test execution and monitoring preferences

[GitHub - CodeGuardian]

---

## 2. pydeps

### Official Source

- **GitHub Repository**: [thebjorn/pydeps](https://github.com/thebjorn/pydeps)
- **PyPI Package**: [pydeps](https://pypi.org/project/pydeps/)
- **Documentation**: [pydeps documentation](https://pythonhosted.org/pydeps/)

### Purpose & Main Features

Pydeps is a Python module dependency visualization tool that creates visual dependency graphs for Python packages by analyzing import statements in source code. It generates SVG or PNG visualizations showing how modules depend on each other, making it easier to understand code structure and identify problematic circular dependencies. [GitHub - pydeps]

Key features:

- **Dependency graph visualization** via SVG or PNG output
- **Circular dependency detection** (highlighted as blue boxes by default)
- **Bytecode-based analysis** that finds imports by examining Python bytecodes
- **Multiple input formats** support (files, directories, installed packages, module names)
- **Configurable filtering** and visualization options
- **Cluster visualization** for external dependencies

[pydeps documentation, GitHub - pydeps]

### How It's Used

The tool is primarily command-line driven. Usage examples:

```bash
# Analyze individual files
pydeps src/myapp/main.py

# Analyze directories
pydeps src/myapp

# Analyze installed packages
pydeps pandas

# Analyze specific modules
pydeps pandas.core
```

The default usage displays the dependency graph in your browser, but limits it to two hops (which includes only the modules that your module imports – not continuing down the import chain). [pydeps documentation]

### Installation Requirements

- **Python package**: `pip install pydeps`
- **External dependency**: Graphviz must be installed separately; the `dot` command must be available on the system PATH [pydeps documentation]

### Output Format & Artifacts

Supported output formats include:

- **SVG** (default format)
- **PNG** (raster image format)

The tool generates intermediate JSON-formatted dependency data and creates visual graph files. An example intermediate format includes module metadata like imports, imported_by relationships, and file paths. [GitHub - pydeps]

### Configuration Options & Common Parameters

**Key Command-Line Options**:

**Output & Display:**
- `-o file` — Write output to specified file
- `-T FORMAT` — Set output format (svg|png)
- `--display PROGRAM` — Specify viewer program
- `--noshow` — Suppress automatic display

**Analysis Filtering:**
- `--max-bacon INT` — Limit nodes to N hops away (default: 2)
- `--max-module-depth INT` — Coalesce deep modules
- `-x PATTERN` — Exclude matching modules
- `-xx MODULE` — Exclude exact module match
- `--only MODULE_PATH` — Include only specified modules

**Graph Visualization:**
- `--rankdir {TB,BT,LR,RL}` — Control graph direction (Top-Bottom, Bottom-Top, Left-Right, Right-Left)
- `--cluster` — Group external dependencies
- `--collapse-target-cluster` — Collapse target package
- `--rmprefix PREFIX` — Remove label prefixes

**Diagnostic Options:**
- `--show-deps` — Display dependency analysis output
- `--show-cycles` — Highlight import cycles only
- `--verbose` — Increase verbosity

[GitHub - pydeps]

**Configuration Files**:

Settings can be defined in configuration files using INI syntax in multiple locations:

- `.pydeps` file in current or home directory
- `pyproject.toml` under `[tool.pydeps]` section
- `setup.cfg` under `[pydeps]` section

Command-line arguments override file-based settings. Configuration hierarchy: command-line > project config > home directory settings. [GitHub - pydeps]

### Limitations

pydeps finds imports by looking for import-opcodes in python bytecodes and only analyzes files that are actually imported. Builtin and C extension modules cannot be analyzed by name. [pydeps documentation]

---

## 3. dot-layered-transform

### Official Source

- **GitHub Repository**: [J4CKVVH173/dot-layered-transform](https://github.com/J4CKVVH173/dot-layered-transform)
- **PyPI Package**: [dot-layered-transform](https://pypi.org/project/dot-layered-transform/)
- **piwheels**: [dot-layered-transform](https://www.piwheels.org/project/dot-layered-transform/)

### Purpose & Main Features

dot-layered-transform is a Python tool for analyzing and visualizing architectural dependencies from DOT graphs, featuring circular dependency detection, layer violation checks, and generation of color-coded, layered DOT diagrams for enhanced readability. It's designed to process outputs from tools like Rust's cargo modules. [GitHub - dot-layered-transform]

The tool is particularly suited for projects using Clean Architecture or layered design patterns.

Key features:

- **Circular dependency detection**: Identifies cycles within the dependency structure
- **Layer violation checks**: Flags dependencies that violate layered architecture rules (domain, application, infrastructure layers)
- **Color-coded visualization**: Generates enhanced DOT diagrams with visual distinction between layers
- **Edge filtering**: Color-codes edges based on their type (owns or uses) and filters to show only relevant connections
- **Analysis output**: Provides detailed reports in text or JSON formats
- **DOT file transformation**: Converts raw dependency graphs into structured, layered visualizations

[GitHub - dot-layered-transform]

### How It's Used

Typical workflow:

1. **Generate DOT file**: Use `cargo modules` or similar tools to create an initial dependency graph
2. **Analyze**: Run `python -m dot_analyzer.cli analyze graph.dot` to detect issues
3. **Transform**: Execute `python -m dot_analyzer.cli transform graph.dot -o output.dot` to generate a layered diagram
4. **Render**: Use Graphviz to convert the enhanced DOT file into PNG or other image formats

[GitHub - dot-layered-transform]

### Installation

```bash
pip3 install dot-layered-transform
```

**Requirements**: Python 3.10+, Graphviz [GitHub - dot-layered-transform]

### Output Format & Artifacts

- **Layered DOT file**: Enhanced DOT format with:
  - Color-coded nodes organized by architectural layer
  - Color-coded edges based on dependency type
  - Filtered edges to reduce visual noise
  - Visually apparent dependency violations compared to original graph

- **Analysis reports**: Text or JSON format detailed dependency analysis
- **Visual diagrams**: PNG, SVG, or other image formats via Graphviz rendering

[GitHub - dot-layered-transform]

### Configuration Options

The tool accepts DOT files and provides command-line options:

- `-o OUTPUT_PATH` — Specify output path for transformed DOT file (if omitted, output to stdout)
- `--format FORMAT` — Specify output format (text, JSON)
- Analysis options for layer violation detection and circular dependency reporting

[GitHub - dot-layered-transform]

---

## 4. skylos

### Official Source

- **PyPI Package**: [skylos](https://pypi.org/project/skylos/)
- **Official Documentation**: [Skylos Documentation](https://docs.skylos.dev/)
- **GitHub Repository**: Referenced in official sources

### Purpose & Main Features

Skylos is an open-source static analysis CLI that identifies code quality issues before they reaches production. As described on PyPI, it finds "dead code, security issues, secrets, quality regressions, and AI-code mistakes" across multiple programming languages. [PyPI - skylos]

**Language Support**: Skylos analyzes Python, TypeScript/JavaScript, Go, Java, Kotlin, PHP, Rust, Dart, C#, C++, and Shell code. [PyPI - skylos]

**Analysis Categories**: 
- Dead-code detection (with framework awareness for FastAPI, Django, Flask, Next.js to reduce false positives)
- Security scanning and vulnerability detection
- Hardcoded credentials/secrets detection
- Dependency vulnerability checking (Software Composition Analysis)
- Code quality metrics (complexity, nesting, structural issues)
- AI-defect verification (hallucinations, invalid API calls)
- Container image scanning and GPU compatibility checks

[Docs - skylos, PyPI - skylos]

### How It's Used

The tool operates as a local-first solution that developers can run directly on their machines or integrate into CI/CD pipelines.

**Basic commands**:

```bash
# First scan
skylos .

# Full audit (dead code, security, secrets, quality, dependencies)
skylos . -a

# Initialize configuration
skylos init

# Generate GitHub Actions workflow
skylos cicd init
```

**Key Features & Options**:

- `--trace`: Runs tests to eliminate false positives from dynamic code patterns
- `--danger`: Detects SQL injection, command injection, and similar vulnerabilities
- `--secrets`: Finds hardcoded credentials
- `--quality`: Checks complexity, nesting, and structural issues (with thresholds like "Complexity: 18 max 10")
- `--sca`: Scans dependencies for known vulnerabilities
- `--upload`: Sends results to dashboard for tracking and collaboration

[Docs - skylos]

### Installation

```bash
# Via pip
pip install skylos

# Via uv
uv pip install skylos
```

Requires Python 3.10+. Verify with `skylos --version`. [Docs - skylos]

### Output Format & Artifacts

Skylos supports multiple output modes for different workflows:

- **JSON**: For programmatic processing
- **SARIF**: For GitHub code scanning integration
- **Pretty-printed terminal reports**: Human-readable CLI output
- **GitLab Code Quality reports**: CI/CD platform integration format
- **Concise CLI output**: Brief summary format
- **Interactive TUI**: Terminal user interface for exploration

[PyPI - skylos]

### Configuration Options & Common Parameters

**Primary Config File**: `pyproject.toml`

Skylos discovers `[tool.skylos]` by walking up from the scan path. For dedicated configs, use `--config-file PATH` or set `SKYLOS_CONFIG_FILE` environment variable. Standalone TOML files may use either `[tool.skylos]` or top-level `[skylos]` sections. [Docs - skylos]

**Core Configuration Sections**:

**Basic Setup**:
```toml
[tool.skylos]
exclude = ["node_modules", "dist"]
```

**Template Files** (extend built-in prompts):
```toml
[tool.skylos.templates]
security = ".skylos/templates/security.md"
quality = ".skylos/templates/quality.md"
```

**Vibe Dictionary** (teach local patterns):
```toml
[tool.skylos.vibe]
extra_phantom_names = ["verify_enterprise_auth"]
extra_phantom_decorators = ["tenant_admin_required"]
extra_credential_names = ["tenant_signing_secret"]
extra_network_timeout_calls = ["vendor_sdk.fetch"]
```

**Dead Code Entrypoints** (mark framework-specific symbols as live):
```toml
[[tool.skylos.dead_code.entrypoints]]
type = "method"
name = ["create", "pre_hook"]
parent = { name = "Main", base_classes = ["Application"] }
path = "src/**"
reason = "project framework lifecycle hook"
```

**Contribution Settings**:
```toml
[tool.skylos.contribution]
collect_local_signals = false
contribute_public_corpus = false
structural_signatures_only = true
```

[Docs - skylos]

**Command-Line Overrides**:

- `--exclude`: Adds to repository excludes
- `--include-folder`: Overrides excluded directories
- `--config-file`: Specifies alternate config location

[Docs - skylos]

**Quality Thresholds** (enforced via pyproject.toml):

Skylos enforces hard thresholds for complexity, nesting, and security risk via configuration to block non-compliant pull requests. Initial configuration can be generated with `skylos init`. [Docs - skylos]

**AI Features** (Optional):

Configure LLM access via environment variables (`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`) for agent review and remediation—not required for core static analysis. [Docs - skylos]

**Initial Configuration**:

"You do not need config for a first scan." Settings like thresholds and exclusions go in `[tool.skylos]` section of `pyproject.toml`. [Docs - skylos]

---

## Sources

### CodeGuardian
- [The-Swarm-Corporation/CodeGuardian on GitHub](https://github.com/The-Swarm-Corporation/CodeGuardian)

### pydeps
- [thebjorn/pydeps on GitHub](https://github.com/thebjorn/pydeps)
- [pydeps on PyPI](https://pypi.org/project/pydeps/)
- [pydeps documentation](https://pythonhosted.org/pydeps/)

### dot-layered-transform
- [J4CKVVH173/dot-layered-transform on GitHub](https://github.com/J4CKVVH173/dot-layered-transform)
- [dot-layered-transform on PyPI](https://pypi.org/project/dot-layered-transform/)
- [dot-layered-transform on piwheels](https://www.piwheels.org/project/dot-layered-transform/)

### skylos
- [skylos on PyPI](https://pypi.org/project/skylos/)
- [Skylos Documentation](https://docs.skylos.dev/)
