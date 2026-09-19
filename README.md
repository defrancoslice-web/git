# 自然灾害灾情数据自动化综合分析辅助决策支撑平台

面向「安全与应急创新」赛项四川省减灾中心企业命题的可运行原型。
五个模块全部跑通：**数据接入清洗 → 多维多层级分析 → 可视化 → 报告生成**，
外面套一层智能体负责意图理解、任务规划、工具调用与结果校验。

## 快速开始

最省事的方式：**双击 `启动.bat`**，它会自动检查环境、准备数据并打开浏览器。
只用命令行的话：

```bash
pip install -r requirements.txt

python scripts/seed_sample_data.py       # 1. 生成模拟灾情数据（故意注入脏数据）
python run_demo.py                       # 2. 一键跑通并打印执行轨迹
python -m disaster_agent.cli serve       # 3. 打开可视化界面 http://127.0.0.1:8000
```

当前版本：**Beta 0.5.1**。Windows 上最省事的方式是双击根目录的 `启动.bat`
（或先跑一次 `创建桌面快捷方式.bat`，之后双击桌面图标即可）。
完整操作手册见 `使用说明.md`，版本变更见 `CHANGELOG.md`。

## 分支约定

| 分支 | 用途 |
| --- | --- |
| `main` | 稳定分支。只接收跑通自检的合并，用于打包发版 |
| `develop` | 日常开发分支。新功能、修 bug 都先提交到这里 |

日常改动提交到 `develop`；确认可用、跑通 `python tests/test_pipeline.py` 之后，
再合并回 `main`、更新 `VERSION` 并打新版本号。

团队分工与执行节奏见 `docs/` 目录：

- `docs/项目计划.md` —— 里程碑、任务清单、关键路径与风险
- `docs/协作框架.md` —— 角色划分、文件所有权、接口冻结、交付标准

其它命令：

```bash
python -m disaster_agent.cli run --agent          # 命令行跑通，附智能体轨迹与清洗日志
python -m disaster_agent.cli ask "近五年洪涝灾害直接经济损失趋势"
python -m disaster_agent.cli catalog               # 查看可用维度与指标
python tests/test_pipeline.py                      # 端到端自检（9 项）
```

## 设计要点

**1. 一条确定性流水线，外面套一层智能体。**
算数、画图、导出全部由普通代码完成；大模型只出现在四个地方：判断这份表是什么、
决定这一列怎么清洗、把业务问题翻译成分析计划、把结果写成报告文字。
因此模型不稳定也不会导致演示翻车，`--model mock` 可以完全离线运行。

**2. 先定数据模型，再写代码。**
所有模块围绕一张统一的「灾情事实表」工作：
一条记录 = 一个行政单元 × 一个灾种 × 一个时间粒度 × 一组损失指标。
字段规范写在 `config/schema.json`，拿到组委会模板后只改配置，不动代码。

**3. 清洗规则优先，模型只做判断。**
单位换算、日期解析、行政区划编码校验都是规则库（`config/cleaning_rules.json`），
数值改写只能由规则执行；每一次修改都写入清洗日志（改了什么、依据什么、影响多少行）。

**4. 分析只保留一个分组聚合入口。**
灾种、时段、区域、损失结构以及自定义维度全部表达为维度参数，
新增分析维度不需要新增分析代码——这正是赛项「自定义维度分析」要考的东西。

**5. 图型由规则表决定。**
`config/chart_rules.json` 按维度类型和基数匹配图型，模型只能在候选里挑，不能自由造图。
每张图同时输出静态 PNG（离线可看）和 ECharts 配置（前端可交互）。

**6. 报告里的数字不经过模型。**
文字用模板骨架生成，所有数值从分析结果对象按槽位注入，并保留来源标记。
如果接入大模型润色，也只允许改措辞，不允许改数字。

## 目录结构

```
disaster-agent/
├── config/                      # 全部规则外置，评委可现场改
│   ├── schema.json              # 字段、指标、维度定义（含 2 个自定义维度）
│   ├── cleaning_rules.json      # 单位换算、缺失值策略、异常值、层级校验
│   ├── chart_rules.json         # 图型选择规则表
│   └── report_outline.json      # 报告章节骨架与槽位
├── data/
│   ├── geo/                     # 行政区划边界（市州 21 个、区县 183 个）
│   ├── reference/regions.json   # 行政区划参照表（演示用最小集）
│   ├── sample/                  # 生成的模拟数据（批量上传演示）
│   └── uploads/                 # 界面上传的文件
├── output/                      # charts / reports / processed
├── disaster_agent/
│   ├── config.py                # 配置加载
│   ├── models.py                # 模块之间传递的数据结构
│   ├── ingest.py                # 模块一（上）：导入与字段比对
│   ├── cleaning.py              # 模块一（下）：清洗与审计
│   ├── analytics.py             # 模块二：统一分组聚合入口
│   ├── charts.py                # 模块三：图型规则 + 渲染
│   ├── report.py                # 模块四：报告生成与 Word/PDF 导出
│   ├── plans.py                 # 标准分析计划库（8 个）
│   ├── pipeline.py              # 五模块流水线
│   ├── sample_data.py           # 模拟数据生成器（含脏数据注入）
│   ├── cli.py                   # 命令行入口
│   ├── agent/                   # 智能体：工具、主循环、大模型适配
│   └── web/                     # 本地可视化界面（仅用标准库）
├── scripts/seed_sample_data.py
├── tests/test_pipeline.py
└── run_demo.py
```

## 赛项要求对照

| 赛项要求 | 实现位置 | 说明 |
| --- | --- | --- |
| Excel 批量上传 | `ingest.py` | 多文件、多工作表、自动探测标题行 |
| 字段与模板完全匹配 | `ingest.py` / `schema.json` 的 `aliases` | 输出字段级比对报告：已映射、未识别、缺失必需字段 |
| 缺失值填充 | `cleaning.py` | 损失类指标填 0 并打 `_imputed_metrics` 标记；关键区域缺失则剔除并记账 |
| 异常值识别 | `cleaning.py` | 按灾种分组 IQR 盖帽 + 业务上下限截断，逐指标记录影响行数 |
| 格式统一 | `cleaning.py` / `cleaning_rules.json` | 多格式日期解析、单位换算（亿元/万元/元、万亩/亩/公顷） |
| 层级关系校验 | `cleaning.py` / `regions.json` | 省—市—县代码前缀一致性 + 名称比对，冲突记录标记待确认 |
| 分灾种分析 | `analytics.py` + `plans.py` | 灾种维度 × 任意指标 |
| 分时段分析 | 同上 | 年 / 季 / 月 / 日 |
| 分区域分析 | 同上 | 省 / 市 / 县 / 乡 |
| 损失结构分析 | `analytics.loss_structure` | 人员伤亡、财产、基础设施、农业、房屋 |
| 自定义维度（≥2） | `schema.json` 的 `custom_season`、`custom_per_capita` | 汛期/非汛期、人均损失分档；界面可现场选维度出图 |
| 趋势类图表 | `chart_rules.json` | 折线图、面积图 |
| 对比类图表 | 同上 | 柱状图、排序条形图 |
| 占比类图表 | 同上 | 环形图 |
| 空间分布图表 | `charts.py` + `data/geo/` | 分级着色图（按行政区划边界分级上色）与热力图（按县级中心点渲染强度），未安装边界文件时降级为排序条形图 |
| 自定义图表（≥1） | 同上 | 灾种 × 灾情等级矩阵热力图 |
| 报告自动生成 | `report.py` + `report_outline.json` | 五章正文 + 附录数据质量说明，含表格与图表 |
| Word / PDF 导出 | `report.py` | python-docx 与 reportlab（内置中文字体，无需字体文件） |

## 拿到组委会数据后要改什么

1. **字段映射**：把真实表头补进 `config/schema.json` 的 `aliases`，或直接改 `fields` / `metrics` 的 `label`。
2. **行政区划参照表**：用完整的四川省行政区划代码表替换 `data/reference/regions.json`（代码读取逻辑不用改）。
3. **清洗参数**：按真实数据情况调整 `cleaning_rules.json` 里的单位换算表、缺失值策略与异常值阈值。

改完先跑 `python -m disaster_agent.cli run --agent`，看字段比对报告里「未识别列」和「缺失必需字段」是否清空。

## 接入真实大模型

默认使用离线规则模型，配置环境变量后自动切换，接口不变：

```bash
set DISASTER_AGENT_API_KEY=sk-xxx
set DISASTER_AGENT_BASE_URL=https://api.openai.com/v1
set DISASTER_AGENT_MODEL=gpt-4o-mini
python -m disaster_agent.cli ask "哪些县的人在洪涝中损失最重"
```

模型只负责生成分析计划（JSON）与报告润色，输出会经过 `analytics` 校验，非法维度或指标会被丢弃并回退。

## 已知边界

- 行政区划参照表是演示用最小集，未覆盖的县只做代码前缀校验，不做名称比对。
- 「空间分布」目前用排序条形图代替分级着色图，接入 GeoJSON 后可在 `charts.py` 增加 `choropleth` 分支。
- 网页端用标准库 HTTP 服务，定位是单机演示，未做并发与鉴权。
- 「单次事件」按记录条数近似，真实数据若要按事件归并，需要补充事件 ID 字段。
