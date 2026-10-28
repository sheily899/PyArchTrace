# 分发与发现

PyArchTrace 通过公开 GitHub 仓库、Skills CLI 安装入口和 OpenAI 插件目录包触达用户。各入口的状态不同，不能把“可以从仓库安装”说成“已被目录收录”。

## GitHub 与 Skills CLI

- 仓库名称、简介、topics 和中英文 README 使用 Python、architecture diagram、software architecture、code analysis、Codex Skill 等用户会搜索的词。
- Skill 位于 `skills/architecture-diagram/`，包含运行所需的规则、Schema 和 OpenAI Skill 元数据。发布前运行 `python scripts/prepare_distribution.py` 同步依赖文件。
- 用户可以通过 GitHub 直接安装：

  ```powershell
  npx skills add sheily899/PyArchTrace --skill architecture-diagram --global --agent codex --yes
  ```

- Skills CLI 的检索和排序由其目录与安装使用信号决定；仓库维护者不能保证特定搜索词必然出现或排名。

## OpenAI 插件目录

- 根目录 `plugin.json` 提供插件目录元数据；可上传包由 `python scripts/prepare_distribution.py` 生成到 `dist/openai-plugin/`。
- 该 ZIP 只包含插件清单、MIT 许可证、图标和完整 Skill 目录，不包含测试夹具、项目分析产物或无关源码。
- 上传和公开发布仍需发布者在 OpenAI 平台完成身份验证、检查结果处理及提交审核。Skills-only 插件可能还有额外的目录资格要求；审核通过前不得宣传为已收录。

## 自然语言调用

安装后，用户可以直接说：

```text
使用 architecture-diagram skill 分析当前 Python 项目。先整理模块分层、证据和主链路给我确认，确认后再生成可交互架构图，并为路由模块增加下钻图。
```

清楚说出“Python 项目”“架构图/时序图/链路图”“源码分析”和“下钻”等任务特征，有助于 Agent 判断是否适用。Skill 的描述会限定它只处理基于 Python 源码的图表任务；它不会让模型对所有用户或所有平台作出推荐保证。
