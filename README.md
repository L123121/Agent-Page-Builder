# 低代码页面搭建平台

基于 **Vue 3 + TypeScript + Vite** 的可视化低代码页面搭建平台，搭配 **Python FastAPI** 后端和 **LangGraph AI Agent**。

## 快速启动

### 前端

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
# 访问 http://localhost:8080
```

### 后端

```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 中的 AI_API_KEY（可选，不配置不影响编辑器功能）
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

> 认证：页面 CRUD / AI 接口要求 JWT 登录（注册即用，见下方「认证」）。**生产部署必须把 `.env` 中的 `JWT_SECRET` 换成随机强密钥**，并配置 `CORS_ORIGINS` 为实际前端域名。

## 认证

- **双 token**：登录返回 access（30 分钟，随请求携带）+ refresh（7 天，仅用于换新）；刷新时轮换签发。密码用 bcrypt 哈希存储
- **页面归属隔离**：`pages.user_id` 绑定创建者，列表/读写/版本/分享均按归属过滤，他人资源返回 404（与不存在同语义，防资源枚举）
- **公开分享**：`GET /api/shared/{token}` 匿名只读（token 为 32 位 hex，取消分享即失效）；分享/取消分享需归属者操作
- **前端**：axios 拦截器自动注入 Bearer；401 单飞刷新（并发只发一次）并重试原请求，失败弹登录框；SSE 流式请求同带 token

```bash
# 认证相关接口
POST /api/auth/register   # 注册（返回双 token）
POST /api/auth/login      # 登录
POST /api/auth/refresh    # 刷新（轮换双 token）
```

## 功能一览

| 功能 | 说明 |
|------|------|
| 拖拽编辑 | 组件拖入画布，支持移动/缩放/旋转/多选 |
| 组件库 | 文本、按钮、图片、表格、图表、图形等 11 种组件 |
| 撤销重做 | 命令模式，支持 300ms 内命令合并 |
| 自动保存 | 脏标记 + 防抖，持久化到 localStorage |
| 版本管理 | 保存/恢复/删除页面快照 |
| 动画系统 | 74 种 CSS 动画，支持入场/离场/强调 |
| 事件绑定 | 跳转链接、弹窗提示、组件联动 |
| 数据请求 | 组件支持 API 数据绑定与定时轮询 |
| HTML 导出 | 导出为自包含独立 HTML 文件 |
| AI 生成 | 对话式页面生成，LLM 自主决策 |
| 页面管理 | FastAPI 后端 CRUD + 分享（JWT 登录 + 用户归属隔离），自动同步到后端，localStorage 离线兜底 |
| 暗黑模式 | 支持明暗主题切换 |

## 项目结构

```
├── frontend/    Vue 3 + TypeScript 前端编辑器
│   ├── src/
│   │   ├── commands/       # 命令模式（14 个命令类）
│   │   ├── components/     # 编辑器 UI
│   │   ├── custom-component/ # 组件库（11 种组件）
│   │   ├── composables/    # 组合式函数
│   │   ├── store/          # Pinia 状态管理
│   │   ├── types/          # TypeScript 类型
│   │   ├── schemas/        # Zod 运行时校验
│   │   └── utils/          # 工具函数
│   └── package.json
├── backend/     Python FastAPI 后端
│   ├── app/
│   │   ├── models/         # ORM 模型
│   │   ├── schemas/        # Pydantic 校验
│   │   ├── routers/        # API 路由
│   │   └── services/       # AI Agent 服务
│   ├── main.py
│   └── requirements.txt
├── start.ps1    Windows 一键启动
├── start.sh     macOS/Linux 一键启动
└── README.md
```

## 技术栈

**前端**: Vue 3, TypeScript, Pinia, Vite, Element Plus, ECharts, Zod, DOMPurify

**后端**: FastAPI, SQLAlchemy, SQLite, LangGraph, LangChain

## 核心设计

- **数据驱动渲染**：页面抽象为 `componentData` JSON，Vue 动态组件渲染
- **命令模式**：14 个命令类，支持撤销/重做/合并/序列化/跨会话持久化
- **组件注册表**：`registerComponent()` 统一注册，元数据驱动属性面板
- **扁平数组 + parentId**：兼顾操作效率与嵌套表达
- **AI Agent**：LangGraph 阶段路由 + 工具白名单；生成和编辑阶段采用“观察 → 单工具执行 → 确定性验证 → 自动修复 → 再验证”的有限闭环
- **画布环境上下文**：Agent 可读取现有组件、锁定与层级状态、选中组件、框选结果、视口尺寸和项目知识
- **安全执行**：工具先在隔离画布快照中运行，通过越界、重叠、文本溢出、内容完整性和颜色对比度检查后才生成最终差异

## Agent 评测（Eval）

`backend/eval/` 提供一套三层评测体系，用于量化 Agent 质量、回归防劣化：

- **tasks.py** — 31 条 golden 任务：生成×12、编辑×6、删除×3、布局×2、交互×2，以及 **6 条对抗性用例**（越界修复、未知组件引用、阶段白名单拒绝、锁定组件重定向、删除不存在组件、planner 误调工具——每条都要求走完「错误 → 反馈 → 自省修正」闭环），每条含初始画布与期望标准
- **scorer.py** — 逐项检查打分（组件覆盖、文本命中、验证器通过、修复轮次、方案产出、自省修正等），`score = 通过项/总项 × 100`
- **judge.py** — LLM-as-Judge 质量评审（0~100，5 维 rubric：内容完整性/组件覆盖/布局/视觉/需求符合度），与规则分互补
- **runner.py** — 双模式运行：
  - **mock 模式**：脚本化 LLM（支持多轮响应脚本，精确回归「犯错→反馈→修正」闭环），不消耗 Token，秒级回归（CI 使用，`--require-pass-rate 100` 门禁）
  - **live 模式**：真实 LLM 全链路，自动模拟多轮交互（选项→确认→生成），量化真实质量（含 judge 分）
- **summary.py** — 聚合最新 mock/live 报告为 Markdown 表格（`python -m eval.summary --write`），保证文档与报告一致
- **golden_suggest.py** — 扫描 agent_runs 运行日志，导出「失败/自省修正 case」为 golden 候选（`python -m eval.golden_suggest --write`），形成线上失败 → 回归用例的飞轮
- **judge_backfill.py** — 对历史报告的 finalCanvas 回溯补测 judge 分，建立评分基线
- **token_benchmark.py** — Token 成本基准（输入侧 + 输入输出总成本双口径）

### 运行日志（可观测性）

每次 Agent 调用（含 live 评测、前端 chat/chat_stream）落库到 `agent_runs` 表：
状态（success / waiting / degraded / error）、修正轮次、最终验证摘要、耗时、
prompt 与回复截断。日志是旁路——落库失败只留 warning，绝不影响主流程。

```bash
python -m eval.golden_suggest --write   # 运行统计 + golden 候选清单
```

```bash
# 回归（CI / 本地快速验证，无需 API key）
cd backend && python -m eval.runner --mode mock

# 真实质量评测（需要 AI_API_KEY）
python -m eval.runner --mode live

# 单任务 / 调整限流延迟 / 汇总报告
python -m eval.runner --mode live --task poster_dance_recruit
python -m eval.runner --mode live --delay 15
python -m eval.summary --write
```

报告输出到 `backend/eval/reports/eval-{mode}-{时间戳}.json`，可对比历史基线；分任务明细表见 `backend/eval/reports/summary.md`（由 `summary.py` 生成）。

### 最新回归结果（mock，31/31 通过）

| 任务 | 类别 | mock | | 任务 | 类别 | mock |
|---|---|---|---|---|---|---|
| poster_dance_recruit | 生成 | ✅ | | edit_button_text | 编辑 | ✅ |
| poster_activity_promo | 生成 | ✅ | | edit_text_color | 编辑 | ✅ |
| form_registration | 生成 | ✅ | | edit_move_component | 编辑 | ✅ |
| poster_lecture | 生成 | ✅ | | edit_font_shrink | 编辑 | ✅ |
| poster_job_fair | 生成 | ✅ | | edit_multi_component | 编辑 | ✅ |
| poster_movie_night | 生成 | ✅ | | delete_component | 删除 | ✅ |
| poster_sports_meet | 生成 | ✅ | | delete_button | 删除 | ✅ |
| form_questionnaire | 生成 | ✅ | | delete_second_text | 删除 | ✅ |
| form_vote | 生成 | ✅ | | layout_center_focus | 布局 | ✅ |
| page_club_intro | 生成 | ✅ | | layout_vertical_stack | 布局 | ✅ |
| page_lost_found | 生成 | ✅ | | empty_canvas_vague | 交互 | ✅ |
| page_notice | 生成 | ✅ | | empty_canvas_style_choice | 交互 | ✅ |
| adv_out_of_bounds_repair | 对抗性 | ✅ | | adv_locked_component_redirect | 对抗性 | ✅ |
| adv_unknown_ref_self_correct | 对抗性 | ✅ | | adv_delete_missing_self_correct | 对抗性 | ✅ |
| adv_rejected_tool_self_correct | 对抗性 | ✅ | | adv_planner_self_correct | 对抗性 | ✅ |

对抗性用例验证的自省修正闭环：`tool_not_allowed`（阶段白名单拒绝）、`unresolved_component_ref`（无效组件引用）、`no_canvas_diff`（动作被跳过/锁定）三类反馈都能让模型在下一轮自主纠正，scorer 的 `SELF_CORRECTED` 检查项逐条断言。

### 已知坑：RPM 限流导致 live 分数失真

StepFun 免费额度有约 10 次/分钟的 RPM 限制。生成类任务一次要走 4~5 轮 LLM 调用
（discover→design→plan→confirm→execute），全量任务连续跑会触发 `429 rate_limited`，
LLM 调用失败后走本地 fallback 返回空画布，导致生成类任务分数异常低（编辑/删除/布局类
只需 1~2 次调用，不受影响）。

**排查特征**：某任务单独跑 100 分、全量连跑却只有 20~40 分，且失败项是
`MIN_COMPONENTS`（0 组件）+ 全部文本缺失——就是撞限流/额度，不是模型质量问题。
两类错误都会触发本地 fallback 产出空画布：`429 rate_limited`（RPM 限流）与
`402 quota_exceeded`（额度耗尽，judge 同时报错）。后者需要充值/换 key 后重跑。

**解法**：
1. live 模式加 `--delay`（默认 7s，可调大）在任务间避让限流窗口；
2. 分任务单独跑（`--task` 单任务不受限流影响）；
3. 平台充值/升级额度后 RPM 上限提高，全量评测即稳定。

### Token 预算控制（防 TPM 限流）

除了 RPM（请求次数），还有 **TPM（每分钟 Token 消耗）** 限流。本项目的 Agent 是
长上下文 + 大输出场景：每轮都携带画布上下文，`generate_page` 一次生成完整组件 JSON，
画布组件多时单次请求可能上万 token，是 TPM 压力最大的地方。

`component_utils.py` 提供了与 Node 版对齐的预算控制：

- **`estimate_tokens()`** — 粗略估算：中文 1 字 ≈ 1 token，英文 4 字符 ≈ 1 token
- **`truncate_by_budget()`** — 二分逼近预算内最大前缀 + 省略标记
- **`build_canvas_context()`** — 接入预算：
  - 组件列表 → `OBSERVATION_TOKEN_BUDGET = 3000`（逐条累积，超限提示「已省略 N 个」）
  - 项目知识 → `PROJECT_KNOWLEDGE_TOKEN_BUDGET = 1000`（token 感知，替代固定字符截断）

效果：画布再大，单次请求上下文也被压在预算内，避免撞 TPM 限流、降低调用成本。

### 评测结果（实测基线，2026-08-12）

以下三项指标均为实测数据，可用 `backend/eval/` 下的脚本复跑验证。

**1. Token 成本降低**（`python -m eval.token_benchmark`，真实画布 + 1 元/M tok 输入 / 3 元/M tok 输出假设）

| 画布规模 | 优化前 | 优化后 | 降低 |
|---|---|---|---|
| 11 组件（真实海报） | 2 559 tok | 1 274 tok | 50.2% |
| 20 组件（代表画布） | 4 012 tok | 1 625 tok | ~60%（输入侧） |
| 120 组件（上限应力） | 20 165 tok | 3 759 tok | 81.4% |

典型 5 轮生成流程（20 组件）：输入侧 token 20 060→8 245（降 58.9%）；计入输出 token 后总成本 ¥0.0327→¥0.0209（**降 36.1%**，输出侧 `generate_page` 全量 JSON 不受截断影响）。

**2. LLM-as-Judge 评分**（`python -m eval.judge_backfill` 回溯基线 + live 实测）

核心海报生成任务（街舞社招新海报）同场景：**judge 分 72 → 100**（11-17 回溯 72 → 12-19 实测 100，修复了输出质量波动；早期 0 分为 RPM 限流空画布所致）。编辑类场景经确定性修复闭环：修改标题字号 65→100、删除图片 10→100，全部达标。

**3. 提效倍数**（平台耗时来自 live 评测计时，约 1.1 分钟/张；手工基线为假设）

| 手工搭建基线（假设） | 提效倍数 |
|---|---|
| 20 分钟（熟练工，素材齐备） | ~18 倍 |
| 60 分钟（含找素材/排版） | ~55 倍 |
| 120 分钟（从零设计） | ~109 倍 |

> 说明：平台端到端耗时（含多轮交互）为实测；手工基线非仓库数据，请按实际场景取值换算：倍数 = 手工耗时 ÷ 1.1 分钟。

## License

MIT
