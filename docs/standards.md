# 标准库

本项目的标准库只保存索引、用途摘要、官方查询链接和工程化配置，不保存标准正文。

## 官方入口

- 国家标准全文公开系统：https://openstd.samr.gov.cn/bzgk/std/index
- 全国标准信息公共服务平台：https://std.samr.gov.cn/

## 文件结构

```text
knowledge/standards/
├─ gb_index.json                         # GB/T 标准索引
└─ profiles/
   └─ gb_mechanical_drawing.json         # GB 机械制图基础 profile
```

## GB 机械制图 Profile

`GB_MECHANICAL_DRAWING` 是后续 ViewPlanner、标注器和 review 的规则入口。

当前包含：

- 投影：默认第一角法，`front/top/left`，俯视图在主视图下方，左视图在主视图右侧。
- 图幅：优先 A3 和 SolidWorks `gb_a3.drwdot`。
- 图线和 CAD：引用机械制图图线标准和 CAD 工程制图规则。
- 视图：引用基本视图、剖视图、断面图相关标准。
- 尺寸：引用尺寸注法、尺寸公差与配合注法。
- 公差：引用一般公差、未注形位公差和 GPS 几何公差。
- 表面结构：引用表面结构表示法。

## 使用边界

- `status` 只是索引核对时的状态记录，后续应定期复查。
- 自动标注规则只能引用标准编号和本地规则摘要，不能替代工程师判断。
- 公开仓库不提交国标正文、企业标准正文或真实客户图纸。
