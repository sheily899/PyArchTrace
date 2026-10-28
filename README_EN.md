<div align="center">

# PyArchTrace

### Evidence-backed architecture diagrams for Python codebases

[简体中文](README.md) · [English](README_EN.md)

<img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
<img alt="Codex Skill" src="https://img.shields.io/badge/Codex-Skill-20232A?logo=openai&logoColor=white">
<img alt="Evidence backed" src="https://img.shields.io/badge/Architecture-Evidence--backed-2563EB">

**Turn Python source evidence into architecture, sequence, and end-to-end flow diagrams.**

</div>

PyArchTrace is a Codex Skill and CLI for Python projects. It helps you organize code modules, verified relationships, and important paths into diagrams you can review. You confirm the structure before rendering. The resulting standalone HTML supports module dragging and drill-down, and exports to SVG and PNG.

> The diagram is grounded in source evidence—not guessed from directory names.

## See what it produces

The examples below show a runtime architecture, a message-processing sequence, and a drill-down into a routing branch. Each is presented as a separate view for its reading purpose, rather than combined into one oversized graphic.

### Runtime architecture: understand the system at a glance

Swimlanes show the entry, orchestration, capability, business-service, and data areas. Cross-cutting governance sits in a side rail. The main view stays at overview level; module relationships can be explored through drill-downs.

<p align="center">
  <img src="docs/images/architecture-overview.png" alt="Example Chinese runtime architecture diagram generated with PyArchTrace" width="100%">
</p>
<p align="center"><sub>Runtime architecture example · layered overview with a governance side rail</sub></p>

### Message sequence: follow a request over time

Participants appear across the top, while messages progress downward in order. This view is useful for tracing a request from user input through the system response.

<p align="center">
  <img src="docs/images/message-sequence.png" alt="Example message-processing sequence diagram generated with PyArchTrace" width="100%">
</p>
<p align="center"><sub>Message sequence example · primary and asynchronous calls shown separately</sub></p>

### Drill-down flow: inspect how routing reaches specific capabilities

Open a module to inspect its internal steps and branches. This keeps the overview readable without hiding the real relationships from the deeper view.

<p align="center">
  <img src="docs/images/agent-routing-drilldown.png" alt="Example agent selection and routing drill-down generated with PyArchTrace" width="100%">
</p>
<p align="center"><sub>Routing drill-down example · parallel branches and their business endpoint</sub></p>

## What it focuses on

- **Traceable evidence:** modules and relationships point back to source paths and locations; unsupported relationships are excluded.
- **Structure review before rendering:** candidate extraction, layering, relationship extraction, and main-path checks produce an intermediate model for your approval.
- **Overview and detail stay readable:** the main diagram presents layers and the primary path; internal behavior belongs in drill-downs or sequence diagrams.
- **Rule-based layout and audit:** deterministic swimlanes, relationship routing, geometry checks, and browser screenshots constrain the result.
- **Editable locally:** open the standalone HTML offline, drag modules, drill down and return, then export SVG or PNG.

## Quick start

Python 3.10 or newer is required.

```powershell
git clone https://github.com/sheily899/PyArchTrace.git
cd PyArchTrace
python -m pip install -e ".[dev,browser]"
```

This installs the CLI, development checks, and browser-capture support. Capturing screenshots requires Chrome or Edge to be available locally. To install only the base CLI:

```powershell
python -m pip install -e .
```

### Use the Skill in Codex

Place the repository in a Skills directory configured for Codex so that `SKILL.md` is at the root of the `architecture-diagram` Skill. Then, in a Python project, ask:

> Use `$architecture-diagram` to analyze this project. Show me the structure review first, and wait for my confirmation before generating the diagrams.

The Skill pauses at the structure checkpoint. It does not render final diagrams or screenshots before explicit confirmation.

### Scan a project with the CLI

```powershell
architecture-diagram scan D:\my-python-project -o D:\my-python-project\docs\architecture-diagram\facts.json
```

The CLI also provides commands for work-order generation, analysis audits, structure review and approval, validation, rendering, and browser capture. See the [analysis stages](references/analysis-stages.md) and [Skill workflow](SKILL.md) for the complete process and options.

## Scope and limitations

- Currently supports **Python projects**. In mixed-language repositories, only the Python subsystem is analyzed; other files are inventoried by path.
- The CLI does not import or execute the analyzed project, and it does not make network calls to model services.
- AST output is used for code navigation. Module responsibilities and runtime relationships still require source reading and evidence checks.
- Static analysis may not discover every dynamic import, reflective call, or configuration-driven relationship. The analysis records its actual coverage and limitations.
- Playwright opens the local page and captures screenshots. Visual review is performed by the active Codex model; the Python package does not include Codex's vision model.

## Documentation and examples

| Topic | Location |
| --- | --- |
| Skill entry point and full workflow | [SKILL.md](SKILL.md) |
| A–D source-analysis rules | [references/analysis-stages.md](references/analysis-stages.md) |
| Architecture layout contract | [docs/layout-contract-v2.md](docs/layout-contract-v2.md) |
| Fan-in, fan-out, and relationship-matrix rules | [docs/edge-group-routing.md](docs/edge-group-routing.md) |
| CLI options | `architecture-diagram --help` |
| Sequence diagram sample data | [examples/sequence-demo.json](examples/sequence-demo.json) |

## License

There is currently no license file in this repository. Please do not assume that the project has been released under a particular open-source license until one is added.
