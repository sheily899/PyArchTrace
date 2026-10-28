# 布局后端与运行边界

架构图优先使用固定泳道布局：层垂直堆叠、层内模块水平排列、治理层放侧边。这使层级和同层基线稳定，不交给图模型手写坐标。

内置链路布局使用确定性拓扑分层与正交路径，适合离线和小中型流程。它会对交叉、节点障碍与折点生成检查报告；复杂拓扑若无法满足简单连线，应拆图，不应靠隐藏边绕开。

## 可选 ELKJS

架构图始终使用固定泳道模板；其可下钻的流程细节图复用架构图的紧凑卡片、中心端口与硬编码正交路由，按端点相对位置确定每条边的横纵方向。普通独立链路图仍可尝试 ELKJS Layered + ORTHOGONAL；时序图使用专用确定性布局。工具不会强制下载 Node 依赖。若项目本地有 Node.js，可在项目目录安装可选包：

```powershell
npm install --no-save elkjs
architecture-diagram render diagram.json -o out --layout-backend elkjs
```

未配置时 `--layout-backend auto` 回退内置布局；显式选择 `elkjs` 但依赖缺失时会报出配置错误。ELK 输出仍须经过正交性、弯折数和真实截图复核；布局引擎通过不等于视觉质量通过。

## 视觉闭环

`capture_html()` 通过真实 Chromium/Chrome/Edge 打开本地 `file://` HTML 并只截取 SVG 图面。`render --capture` 会分别生成主图及所有嵌套子图的 PNG、SVG、HTML 和诊断报告。`run_review_loop()` 每轮把每张图的 PNG、几何结果和审查提示交给 `reviewer(image_path, prompt, geometry_report)`。这个 callback 必须连接到能看图的 Agent；如果不提供，函数为每个视图生成 `round-XX-{图编号}-visual-review-request.json` 并明确返回 `pending_visual_review`。当前 Python 进程不会自行调用 Codex 内部视觉模型。

最多四轮；通过条件为视觉评估 pass、几何检查通过、浏览器无页面错误和 DOM 无溢出。拆图是用户决策，不会由工具自动删除模块/边。
