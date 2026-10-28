<div align="center">

# PyArchTrace

### 让 Python 架构图有据可查，也能看懂、下钻和复核

[简体中文](README.md) · [English](README_EN.md)

<img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
<img alt="Codex Skill" src="https://img.shields.io/badge/Codex-Skill-20232A?logo=openai&logoColor=white">
<img alt="Evidence backed" src="https://img.shields.io/badge/Architecture-Evidence--backed-2563EB">

**从源码证据出发，生成中文架构图、时序图与端到端链路图。**

</div>

PyArchTrace 是面向 Python 项目的 Codex Skill 与 CLI 工具。它帮助你把代码中的模块、真实关系和关键路径整理成可审阅的图；结构先由你确认，再进入渲染。生成的单文件 HTML 支持拖动、逐层下钻，并可导出 SVG 与 PNG。

> 图不是从目录名猜出来的：模块和关系都要能回到源码证据。

## 看看它能生成什么

下面的图分别展示运行时分层、一次消息处理时序，以及一个调度分支的内部关系。它们是单独的视图，按阅读场景放在这里，而不是拼成一张总览海报。

### 运行时架构：先看清系统由哪些部分组成

分层泳道展示入口、编排、能力、业务服务和数据；横切治理能力放在侧栏。主图保持概览，具体模块关系可以继续下钻。

<p align="center">
  <img src="docs/images/architecture-overview.png" alt="PyArchTrace 生成的中文运行时架构图示例" width="100%">
</p>
<p align="center"><sub>运行时架构示例 · 分层总览与治理侧栏</sub></p>

### 消息时序：沿时间顺序读一条请求

时序视图把参与模块放在顶部，把消息按发生顺序向下展开，适合追踪从用户输入到系统回复的过程。

<p align="center">
  <img src="docs/images/message-sequence.png" alt="PyArchTrace 生成的消息处理时序图示例" width="100%">
</p>
<p align="center"><sub>消息处理时序示例 · 主链路与异步调用分开展示</sub></p>

### 下钻链路：看清调度如何分发到具体能力

从主图进入模块细节后，可以把一个高层职责拆成可核对的步骤和分支关系，而不把主图挤成一张密集的调用网。

<p align="center">
  <img src="docs/images/agent-routing-drilldown.png" alt="PyArchTrace 生成的智能体选择与分派下钻图示例" width="100%">
</p>
<p align="center"><sub>调度下钻示例 · 展示并行分支及其业务出口</sub></p>

## 它重点解决什么

- **证据可追溯**：模块与关系附源码路径和位置；没有证据的关系不进入图。
- **先确认结构**：按候选提取、分层、关系提取、主路径校验逐步形成中间结构；你确认后才渲染最终图。
- **主图与细节分开**：主图说明层次与主链路；模块内部处理和真实调用关系放到下钻图或时序图。
- **布局和审计有规则**：确定性泳道布局、关系路由、几何检查和浏览器截图验收共同约束输出。
- **本地可编辑**：HTML 离线打开；可以拖动模块、下钻、返回，并导出 SVG/PNG。

## 快速开始

需要 Python 3.10 或更高版本。

```powershell
git clone https://github.com/sheily899/PyArchTrace.git
cd PyArchTrace
python -m pip install -e ".[dev,browser]"
```

这会安装 CLI、开发检查工具和浏览器截图支持。截图需要本机可用的 Chrome 或 Edge。只使用 CLI 的扫描、校验和绘图功能时，可安装基础包：

```powershell
python -m pip install -e .
```

### 在 Codex 中使用 Skill

将仓库放入当前 Codex 配置的 Skills 目录，使 `SKILL.md` 位于 `architecture-diagram` Skill 根目录。然后在目标 Python 项目中提出：

> 使用 `$architecture-diagram` 分析这个项目，先给我结构审阅；等我确认后再生成架构图。

Skill 会先停在结构确认点。没有收到明确确认，不会生成最终图或截图。

### 使用 CLI 盘点项目

```powershell
architecture-diagram scan D:\my-python-project -o D:\my-python-project\docs\architecture-diagram\facts.json
```

CLI 也提供提示工作单生成、分析审计、结构审阅、签发、校验、渲染和浏览器截图等命令。完整的 A–D 工作流和参数见 [分析阶段说明](references/analysis-stages.md) 与 [Skill 使用规范](SKILL.md)。

## 工作边界

- 当前支持 **Python 项目**。混合仓库只分析 Python 子系统；其他语言文件只做路径盘点。
- CLI 不导入或执行待分析项目，也不联网调用模型服务。
- AST 结果只用于代码导航；模块职责与运行时关系仍需回读源码并核对证据。
- 动态导入、反射和配置驱动调用可能无法由静态扫描完整发现；分析产物会记录实际覆盖范围和边界。
- Playwright 负责打开本地页面并截图；图像视觉复核由当前 Codex 模型执行，Python 包本身不携带 Codex 视觉模型。

## 文档与示例

| 内容 | 位置 |
| --- | --- |
| Skill 入口与完整工作流 | [SKILL.md](SKILL.md) |
| A–D 源码分析规则 | [references/analysis-stages.md](references/analysis-stages.md) |
| 架构图布局契约 | [docs/layout-contract-v2.md](docs/layout-contract-v2.md) |
| 扇入、扇出与关系矩阵规则 | [docs/edge-group-routing.md](docs/edge-group-routing.md) |
| CLI 参数 | `architecture-diagram --help` |
| 时序图示例数据 | [examples/sequence-demo.json](examples/sequence-demo.json) |

## 许可

仓库当前未附带许可证文件。添加许可证前，请先确定希望采用的开源许可；在此之前，请勿将本项目视为已授予特定开源许可。
