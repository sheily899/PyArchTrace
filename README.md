# PyArchTrace

**Evidence-backed architecture diagrams for Python codebases.**

PyArchTrace 是一个面向 Python 项目的 Codex Skill 与 Python CLI 工具。它引导 Agent 阅读源码、整理模块与真实调用关系，再生成中文架构图、时序图和端到端链路图。每个模块和关系都要求有源码证据；图可在浏览器中下钻查看，并导出为可编辑的 HTML 与 SVG。

```text
Python 源码 → 证据分析 → 结构确认 → 可交互架构图
```

## 为什么用 PyArchTrace

- **关系有据可查**：节点和连线关联到源码路径与行号；没有代码证据的关系不画。
- **先审结构，再渲染**：按候选提取、分层、关系提取、主路径校验逐步分析，等待用户确认结构后才生成最终图。
- **图面可检查、可调整**：固定分层、确定性布局、几何审计、真实浏览器截图；模块支持拖动和下钻。
- **边界清楚**：CLI 不执行待分析项目，也不调用在线服务；使用 Skill 时，源码由当前 Agent 按其运行环境处理。

## Quick start

```powershell
git clone https://github.com/sheily899/PyArchTrace.git
cd PyArchTrace
python -m pip install -e ".[dev,browser]"
```

上述命令安装 CLI。要在 Codex 中调用 Skill，需将仓库放入当前 Codex 配置的 Skills 目录；Skill 名称仍为 `architecture-diagram`。

安装后，在目标 Python 项目中请求：

> 使用 `$architecture-diagram` 分析这个 Python 项目，先给我结构审阅，等我确认后再生成架构图。

只安装基础 CLI、不需要浏览器截图时，执行 `python -m pip install -e .`。浏览器截图需要本机 Chrome 或 Edge。

## 项目范围

工具不执行被分析项目，也不把静态索引猜测成业务事实。当前只支持 Python 项目；混合仓库只分析 Python 子系统，非 Python 文件仅作路径盘点。只有 Python 源码直接证明跨边界调用时，才把对端标为外部端点，不分析对端内部结构。Python AST 仅提供代码导航事实，业务语义与运行时关系仍需结合源码路径和行号核实。Playwright 用于浏览器截图；视觉理解由当前 Codex 模型完成。

## 安装

需要 Python 3.10 或更高版本。绘图、扫描、校验只用 Python 标准库；开发测试可安装 `.[dev]`。浏览器截图需要 `.[browser]` 和本机 Chrome/Edge。没有自动安装浏览器，也不联网。

```powershell
python -m pip install -e ".[dev,browser]"
```

若只需要图而不截图：

```powershell
python -m pip install -e .
```

## 完整工作流

```powershell
architecture-diagram scan D:\my-python-project -o D:\my-python-project\docs\architecture-diagram\facts.json
architecture-diagram abstract-prompt D:\my-python-project\docs\architecture-diagram\facts.json -o D:\my-python-project\docs\architecture-diagram\abstract.md
```

默认工作单提供完整 facts 与两份完整 schema。分阶段筛选为显式 opt-in：A 阶段可用 `--slim-input --stage A`；B/C/D 还需 `--analysis <已有 analysis.json>`；C 阶段再指定 `--module-id <模块ID>`，一次只处理该模块相关关系。每份阶段工作单会记录提供与省略的 facts、analysis 和 schema 范围；省略只表示不重复塞入提示，不表示无需阅读对应源码。默认继续使用完整兼容模式。

优化扫描模式用一次目录遍历完成文件盘点和 Python 文件发现，并在 facts 中记录排除规则版本、规则清单和实际跳过路径。它通过 `--optimized-scan` 显式启用；默认扫描保留兼容模式。优化模式默认跳过测试/评测/脚本、生成与缓存目录、虚拟环境、依赖目录、隐藏目录及基线/历史输出目录；可用 `--exclude-dir NAME` 增加排除项，或用 `--include-dir NAME` 覆盖默认排除。覆盖按目录名生效，并会写入 `scanConfig`。

把工作单与项目源码交给 `SKILL.md` 描述的流程。A–D 的完整规则唯一维护于 `references/analysis-stages.md`，Skill 与 CLI 工作单都从此处引用或生成阶段说明。架构图必须依次完成 A 候选、B 分层、C 关系、D 主路径审计，将阶段结果写入 `analysis.json`，并在图边通过 `relationIds` 回指已取证关系。完成 analysis 后，用命令从它自动生成三份派生清单，不要手工编写：

```powershell
architecture-diagram analysis-reports D:\my-python-project\docs\architecture-diagram\analysis.json -o D:\my-python-project\docs\architecture-diagram
```

然后运行审计、校验和渲染：

```powershell
architecture-diagram audit-analysis D:\my-python-project\docs\architecture-diagram\analysis.json D:\my-python-project\docs\architecture-diagram\diagram.json --source-root D:\my-python-project -o D:\my-python-project\docs\architecture-diagram\analysis-audit.json
architecture-diagram enrich-details D:\my-python-project\docs\architecture-diagram\analysis.json D:\my-python-project\docs\architecture-diagram\diagram.json D:\my-python-project\docs\architecture-diagram\facts.json -o D:\my-python-project\docs\architecture-diagram\diagram.enriched.json
architecture-diagram review-structure D:\my-python-project\docs\architecture-diagram\analysis.json D:\my-python-project\docs\architecture-diagram\diagram.enriched.json --facts D:\my-python-project\docs\architecture-diagram\facts.json --source-root D:\my-python-project -o D:\my-python-project\docs\architecture-diagram\structure-review.json
# 把结构审阅结果交给用户并等待明确回复“确认”；确认前不得渲染或截图。
architecture-diagram approve-structure D:\my-python-project\docs\architecture-diagram\analysis.json D:\my-python-project\docs\architecture-diagram\diagram.enriched.json --facts D:\my-python-project\docs\architecture-diagram\facts.json --review D:\my-python-project\docs\architecture-diagram\structure-review.json --confirmation 确认 -o D:\my-python-project\docs\architecture-diagram\structure-approval.json
architecture-diagram validate D:\my-python-project\docs\architecture-diagram\diagram.enriched.json
architecture-diagram render D:\my-python-project\docs\architecture-diagram\diagram.enriched.json --analysis D:\my-python-project\docs\architecture-diagram\analysis.json --facts D:\my-python-project\docs\architecture-diagram\facts.json --review D:\my-python-project\docs\architecture-diagram\structure-review.json --approval D:\my-python-project\docs\architecture-diagram\structure-approval.json --source-root D:\my-python-project -o D:\my-python-project\docs\architecture-diagram --capture
```

布局/审阅缓存为显式 opt-in：在 `validate`、`review-structure`、`approve-structure` 和 `render` 命令追加 `--reuse-layout-cache`。缓存位于图 JSON 同级的 `.architecture-diagram-cache/`；IR、布局版本、后端参数、审计实现或任一证据源码变化都会换缓存键并重新计算。它只复用完整审阅结果和布局，不跳过证据、结构签发、视觉验收或质量检查。默认不启用缓存。

`audit-analysis` 检查候选是否逐项处置、模块和关系是否有证据、主图密度复核是否与实际节点一致、低于每层 3–5 个软目标时是否记录二次拆分结论、每个主图模块是否完成拆分信号自检、图节点是否均对应分析模块且每个分析模块均已绘出、是否有分析关系未进入主图/子图、图边端点方向是否与关系一致，以及已声明主路径是否有向连通。主图少于 12 个时必须记录证据支持的范围例外。它还要求 `coverageReview.moduleReviews` 对每个模块列出与关系清单一致的全部入边/出边、分支检查状态和未建模动作；漏记边或未解释动作会使审计失败。提供 `--source-root` 时还核查主图和所有下钻节点/关系的证据路径及行号；远程仓库可省略该参数并提供证据 URL。结构审计仍不能自动证明语义拆分和关系穷尽，因此分析者必须逐个回读源码并填写复核清单。

完整视觉复核通过 `architecture-diagram review-loop` 准备截图和审查请求；当前 Codex 视觉 Agent 看图后返回 JSON，再用 `apply-review` 应用修正并重新渲染。具体 Skill 边界、最多四轮和通过条件见 [SKILL.md](SKILL.md)。

## 子图、状态与证据

- `nodes[].drilldown` 指向 `subDiagrams[].id`；架构 HTML 首屏只显示图和精简工具栏。点击模块显示结构化详情面板，点击模块右上角下钻图标进入内部图，并可逐级返回。入口/出口节点保留与父图的上下文。
- 流程类下钻图定义自己的逻辑步骤泳道，不复用父架构层作为布局列；同一处理阶段的并行节点可共用泳道，串行关系按阅读方向排列。
- 架构分析先生成 `modules.md`、`relations.md` 与 `main-paths.md`：分别列出模块、所有已证实关系、逐层数量/密度复核和主链路校验。主图模块数硬范围为 12–25；每层 3–5 个是软目标，不得为凑数虚构或合并模块。不存在的层保持缺席。
- 接入、编排、能力、业务、数据/外部依赖、治理是职责词汇表，不是每个项目的必备六层。Agent 工具或其他领域项目若没有某层，应记录“未发现”及依据，不用模板补造业务模块。
- `implemented`、`partial`、`config_only`、`unknown` 是实现证据元数据，不作为模块类别；架构图卡片和交互页均不显示实现状态徽标。
- `nodes[].evidence` 和 `edges[].evidence` 保存相对路径与行号。主图与下钻图的每个节点、每条边都须有证据；提供 `--source-root` 时逐一核对路径和行号。
- 标题、说明、连线标签、图层名必须使用中文业务含义。英文代码名仅可作为中间 JSON 的内部 ID 或证据，不可渲染。

## 图类型与布局

- 架构图新契约（`layout.contractVersion: 2`）：固定 1440px 画布和字体；卡片统一宽度与 64px 高度，标题单行。主图只在相邻展示泳道的预留通道画层间主流向，不连接具体卡片；主链路在顶部用编号文字表达。每层按 1、2–5、6–10、11+ 个模块采用单卡居中、单排、均衡双排或职责分组规则；11+ 模块必须先有证据支持的职责分组。所有模块仍须有证据，主图 12–25 个模块为硬范围，证据确实不足时记录例外。
- 架构模板按 IR 信号选择：A 分层泳道（默认），B 离线/在线双管线，C 内核/扩展，D 部署分区。模板及选择理由写入布局审阅报告。C/D 展示分组不等于源码层级；展示名仍须由代码证据支持。无法判定模板时回落 A 并记录默认选择。
- 治理、安全、监控等横切职责放在右侧“贯穿所有层”侧栏，不进入主流向；侧栏卡片与普通模块使用相同尺寸。
- 时序图：参与者上方横向排列，消息按 `order` 向下。
- 链路图：按拓扑分层，使用正交线；支持内置确定性布局。可选 ELKJS layered 后端见 `docs/layout-backends.md`。
- 下钻/链路关系先识别一对一、扇出、扇入和双向边组；三条以上的分支用途写在来源卡片固定标签位，多对多自动切换关系矩阵。细则与审计项见 `docs/edge-group-routing.md`。
- 相同 IR、字体环境和模板选择产生相同初始布局。所有自动 x/y 位置由布局器计算；拖动位置只有在用户明确编辑后才写入 IR。位置导致审计失败时退回自动布局并提示用户。
- 每条主图层间线都要有源码证据，最多连接相邻展示泳道；线段走层间通道中心，不进入卡片区。双管线允许按证据向上或向下连接两条管线；其他模板按展示顺序向下连接。
- 几何质量报告也检查节点与泳道是否完整落入 SVG 画布，避免截图边缘裁切。
- 内容密度审计还检查画布宽高、宽高比、卡片统一尺寸、同层居中、字号、文字长度、证据和层间关系。颜色按标准层类型使用固定浅色主题；扩展/部署分组使用中性色；图例列出图中使用的层色与层间连接。
- 所有图以 SVG 作为可缩放矢量输出；HTML 内嵌图形、数据和脚本，不依赖 CDN。

## HTML 交互能力

架构图单文件 HTML 提供拖动模块、下钻/返回、导出 PNG/SVG 和重置布局；点击模块可查看固定字段详情。主图层间箭头锚定相邻泳道边界中心，拖动卡片不改变它们；下钻关系图继续使用端口路由和自动重布线。各视图的拖动位置保存在浏览器本地 `localStorage`，不向外传输。架构图不开放新增/删除模块或连线、改字、JSON 导入/导出等复杂编辑功能。时序图与链路图继续沿用原有交互方式，不受架构图交互调整影响。

架构图必须先完成 `review-structure` 并将模块表、层间主流向、主链路、coverage、硬约束和软约束警告交给用户确认。只有收到明确确认后才能签发凭据并渲染或截图；凭据绑定 `analysis.json`、`diagram.json`、`facts.json` 和结构审阅报告，输入变化即失效。

## 测试与示例

```powershell
python -m pytest -q
architecture-diagram render examples\sequence-demo.json -o outputs\sequence-demo --capture
```

布局压力 IR 位于 `tests/layout_fixtures/`，Pytest 会按当前契约转换冻结输入并执行校验与几何审计；扇入、扇出和多对多另有专门的路径结构断言。

`examples/sequence-demo.json` 展示时序布局；`examples/demo_project` 供 Python AST 扫描测试。`tests/layout_fixtures/` 中的固定项目 IR 仅作跨项目布局回归，不是推荐层级、模块或领域模板，也不参与新项目分析。

架构示例必须按完整工作流经过结构审阅与用户确认后才可渲染。确认后，`render --capture` 会为主图和每张嵌套子图分别输出独立 PNG、SVG、HTML 与浏览器诊断；PNG 截取 SVG 图面本身，不把编辑工具栏混入图像。

## 当前限制

1. 当前仅支持 Python 项目。Python AST 无法完整捕获动态导入、反射、运行时依赖注入或配置驱动调用，具体覆盖范围必须写入 coverage；混合仓库中的非 Python 内部结构不在分析范围内。
2. 图上的业务语义和关系需要模型阅读源代码并引用证据；不会把文件夹名猜成业务层。
3. 架构图新契约采用确定性泳道/模板布局，不做自由拓扑布线；分组证据不足、层间关系不符合模板或固定字号下无法容纳时会审计失败，需要调整结构或拆图。
4. Python 端不持有 Codex 内部视觉模型。Agent 调用 `run_review_loop(... reviewer=callback)` 可接入视觉复核；没有 callback 时返回 `pending_visual_review`。
5. 浏览器内的快速重排是确定性启发式，复杂图仍应导出 JSON，由 CLI 生成并重新检查几何与截图。
