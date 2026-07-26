# 低代码页面搭建平台

基于 **Vue 3 + TypeScript + Vite** 的可视化低代码页面搭建平台，搭配 **Python FastAPI** 后端和 **LangGraph AI Agent**。

## 快速启动

### 前端

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
# 访问 http://localhost:5173
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

## 功能一览

| 功能 | 说明 |
|------|------|
| 拖拽编辑 | 组件拖入画布，支持移动/缩放/旋转/多选 |
| 组件库 | 文本、按钮、图片、表格、图表、图形等 10 种组件 |
| 撤销重做 | 命令模式，支持 300ms 内命令合并 |
| 自动保存 | 脏标记 + 防抖，持久化到 localStorage |
| 版本管理 | 保存/恢复/删除页面快照 |
| 动画系统 | 74 种 CSS 动画，支持入场/离场/强调 |
| 事件绑定 | 跳转链接、弹窗提示、组件联动 |
| 数据请求 | 组件支持 API 数据绑定与定时轮询 |
| HTML 导出 | 导出为自包含独立 HTML 文件 |
| AI 生成 | 对话式页面生成，LLM 自主决策 |
| 页面管理 | FastAPI 后端 CRUD，无认证，直接使用 |
| 暗黑模式 | 支持明暗主题切换 |

## 项目结构

```
├── frontend/    Vue 3 + TypeScript 前端编辑器
│   ├── src/
│   │   ├── commands/       # 命令模式（13 个命令类）
│   │   ├── components/     # 编辑器 UI
│   │   ├── custom-component/ # 组件库（10 种组件）
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
│   │   ├── services/       # AI Agent 服务
│   │   └── middleware/     # JWT 认证
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
- **命令模式**：13 个命令类，支持撤销/重做/合并/序列化/跨会话持久化
- **组件注册表**：`registerComponent()` 统一注册，元数据驱动属性面板
- **扁平数组 + parentId**：兼顾操作效率与嵌套表达
- **AI Agent**：LangGraph 单节点 + 5 工具函数，LLM 自主决策

## License

MIT