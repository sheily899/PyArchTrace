# PyArchTrace 发布素材

## 一句话介绍

PyArchTrace 是面向 Python 项目的 Codex Skill 与 CLI：依据源码证据梳理模块、分层和真实关系，生成可交互、可下钻的中文架构图、时序图与链路图。

## 中文发布文案

读代码时，最难的往往不是找到文件，而是看清系统由哪些部分组成、请求经过哪些模块、分支最后去了哪里。

我做了 PyArchTrace：一个面向 Python 项目的 Codex Skill + CLI。它先从源码整理模块、关系和主链路，让你确认结构后，再生成可拖动、可下钻的架构图、时序图和业务链路图。图可以导出为 SVG、PNG 或离线 HTML。

它更适合“带着问题读项目”：比如追一次请求、看某个 Agent 的分支、确认某个服务实际依赖哪些数据。静态分析仍有边界，动态导入和配置驱动的关系需要结合源码进一步核对。

GitHub: https://github.com/sheily899/PyArchTrace

## English launch copy

Reading a codebase is easier when you can see its modules, request paths, and branches together.

PyArchTrace is a Codex Skill and CLI for Python projects. It grounds module and relationship maps in source evidence, asks you to review the structure, then creates interactive architecture, sequence, and flow diagrams with drill-down. Export the result as SVG, PNG, or standalone HTML.

It is designed for focused codebase exploration: trace a request, inspect an agent’s branches, or see which data stores a service actually uses. Generated diagram labels are currently in Chinese, and static analysis still needs source review for dynamic or configuration-driven behavior.

GitHub: https://github.com/sheily899/PyArchTrace

## 30 秒演示顺序

1. 在 Codex 中输入：“使用 `$architecture-diagram` 分析当前 Python 项目，先给我确认模块分层和主链路。”
2. 展示模块表、证据路径和主链路，确认结构。
3. 展示生成后的总览图：按层阅读模块，沿主链路找到关键节点。
4. 点击模块进入下钻图，展示一个真实的内部调用分支，再返回总图。
5. 拖动模块并展示连线跟随，最后导出 SVG 或 PNG。

## 建议关键词

`python` · `codex` · `agent-skills` · `software-architecture` · `architecture-diagram` · `code-analysis` · `developer-tools`

## 发布前保持准确

- 当前分析范围是 Python；混合仓库只分析 Python 子系统。
- 图中文字当前为中文；README 提供中英文版本。
- 不要把静态扫描描述成完整运行时观测；动态导入、反射及配置驱动关系仍需人工核对。
- 本文是可复制的发布素材，不会自动向社交平台发布。
