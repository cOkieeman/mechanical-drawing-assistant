# 仓库结构

```text
mechanical-drawing-assistant/
├─ src/mechanical_drawing_assistant/  # Python 源码
├─ tests/                             # pytest 测试
├─ knowledge/                         # 规则库、特征库、标准索引
├─ samples/                           # 可提交的任务样例，不放真实 CAD 文件
├─ scripts/                           # 本地辅助脚本
├─ docs/                              # 工作流、集成、路线图、项目记录
├─ external/                          # 外部参考源码，本地忽略
├─ output/                            # 生成结果，本地忽略
└─ .github/workflows/                 # GitHub Actions
```

## 可提交内容

- 源码、测试、文档、规则索引、样例 job。
- 小型、脱敏、可公开的 JSON 样例。

## 不提交内容

- 真实加工图纸、客户资料、SolidWorks 模型、DWG/DXF/PDF 输出。
- `output/`、`external/`、`.venv/`、工具缓存。
- 国标或企业标准原文，除非明确有可再分发授权。

## 迭代入口

- 当前能力和使用方式见 [README.md](../README.md)。
- 后续开发任务书见 [development_task_book.md](development_task_book.md)。
- 详细流程见 [workflow.md](workflow.md)。
- 视图规划器说明见 [view_planner.md](view_planner.md)。
- 视图复查器说明见 [view_review.md](view_review.md)。
- 标准库说明见 [standards.md](standards.md)。
- 后续路线见 [roadmap.md](roadmap.md)。
- 过程记录见 [project/progress.md](project/progress.md)。
