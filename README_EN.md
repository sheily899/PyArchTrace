<div align="center">

# PyArchTrace

### Turn Python code into architecture diagrams you can explore

[简体中文](README.md) · [English](README_EN.md)

<img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
<img alt="Codex Skill" src="https://img.shields.io/badge/Codex-Skill-20232A?logo=openai&logoColor=white">

**Describe what you want to understand. PyArchTrace turns Python source into architecture, sequence, and business-flow diagrams.**

</div>

Start with the system overview, then open a module to see how it works inside. Diagrams are grounded in source code, can be rearranged and explored in the browser, and can be exported as SVG or PNG.

<p align="center"><b>Describe the goal → Review the structure → Explore the diagram</b></p>

## From overview to detail

### Runtime architecture: what is the system made of?

Layers follow the responsibilities found in the project code, such as entry points, orchestration, capabilities, business services, and data. Cross-cutting concerns appear in a side rail; missing layers are not invented to fit a template.

<p align="center">
  <img src="docs/images/architecture-overview.png" alt="Runtime architecture overview example" width="100%">
</p>
<p align="center"><sub>Runtime architecture overview · layers and cross-cutting governance</sub></p>

### Message sequence: what happens during a request?

Sequence diagrams lay out participants and messages over time, making it easier to follow a request from user input through processing to the response.

<p align="center">
  <img src="docs/images/message-sequence.png" alt="Message-processing sequence diagram example" width="100%">
</p>
<p align="center"><sub>Message sequence · follow a request and response over time</sub></p>

### Drill into a module: where do its branches lead?

Open a module from the overview to inspect its internal steps, parallel branches, and business endpoints. Return to the parent view without losing context.

<p align="center">
  <img src="docs/images/agent-routing-drilldown.png" alt="Agent-routing drill-down example" width="100%">
</p>
<p align="center"><sub>Routing drill-down · explore branches and their processing endpoints</sub></p>

## Call the Skill in plain language

You do not need to write JSON, place nodes by hand, or design arrow paths. Tell the Skill where the project is, which flow you care about, and what you want to learn. It presents the structure for your confirmation before generating the final diagram.

**Generate a project overview**

```text
Use `$architecture-diagram` to read this Python project and map its runtime architecture from the actual code responsibilities. Show me the layers and primary path first; wait for my confirmation before generating the interactive diagram.
```

**Trace an end-to-end request**

```text
Use `$architecture-diagram` to draw a sequence diagram for “user submits a query through results returned.” Show the modules, capabilities, and data reads or writes along the way.
```

**Explore a module in detail**

```text
Add a drill-down for the “knowledge retrieval” module. Show how the query is built, retrieved, ranked, and returned.
```

**Set the analysis scope**

```text
Focus on the online request path. Skip tests, offline evaluations, and deployment files. Include only relationships supported by the Python source.
```

You can also say “focus on order processing,” “explain the human handoff path,” or “expand intent recognition” to focus the diagram on what you need to understand.

## What you can do with the result

- **Three views:** runtime architecture, sequence diagrams, and end-to-end flows.
- **Interactive drill-down:** open a module, explore its internal relationships, and return to the overview.
- **Rearrange the diagram:** drag modules and let related arrows update; restore the automatic layout at any time.
- **Share and edit:** export a crisp PNG or SVG, or open the standalone HTML offline.
- **Trace back to code:** modules and relationships link to source locations for follow-up.

## Quick start

Python 3.10 or newer is required.

```powershell
git clone https://github.com/sheily899/PyArchTrace.git
cd PyArchTrace
python -m pip install -e ".[dev,browser]"
```

Place the repository in your Codex Skills directory as `architecture-diagram`, then call it with natural-language prompts like the examples above. Browser screenshots require Chrome or Edge installed locally. To use only the CLI, run `python -m pip install -e .`.

Example CLI project scan:

```powershell
architecture-diagram scan D:\my-python-project -o D:\my-python-project\docs\architecture-diagram\facts.json
```

## Scope

- Currently intended for **Python projects**; mixed-language repositories are analyzed only for their Python subsystem.
- The tool does not import or execute the project being analyzed. Dynamic imports, reflection, and configuration-driven relationships may not be fully discovered by static scanning.
- Python code provides navigation clues; module responsibilities and calls are grounded in source reading.

## Further reading

[Skill guide](SKILL.md) · [Source-analysis workflow](references/analysis-stages.md) · [Layout rules](docs/layout-contract-v2.md) · [Relationship routing](docs/edge-group-routing.md) · [Sequence example](examples/sequence-demo.json)

## License

No license file is included yet, so the repository does not currently declare a specific open-source license.
