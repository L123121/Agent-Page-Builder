# Vue3 低代码可视化页面搭建平台

<p align="center">
  <img src="https://img.shields.io/badge/Vue-3.2+-brightgreen.svg" alt="vue">
  <img src="https://img.shields.io/badge/Vite-6.x-blue.svg" alt="vite">
  <img src="https://img.shields.io/badge/Pinia-2.x-yellow.svg" alt="pinia">
  <img src="https://img.shields.io/badge/Element--Plus-2.x-green.svg" alt="element-plus">
  <img src="https://img.shields.io/badge/TypeScript-5.x-blue.svg" alt="typescript">
  <img src="https://img.shields.io/badge/ECharts-5.x-orange.svg" alt="echarts">
  <img src="https://img.shields.io/badge/License-MIT-orange.svg" alt="license">
</p>

> 一个基于 **Vue 3** + **TypeScript** + **Vite** 的低代码可视化页面搭建平台，通过组件拖拽与配置化方式快速生成业务页面，支持复杂交互编辑与实时预览，搭配 Python FastAPI 后端实现页面持久化，以及 AI Agent 对话式页面生成。

---

## 系统架构

平台采用经典的三栏式编辑器布局：

```
┌─────────────┬─────────────────────────┬─────────────┐
│             │                         │             │
│  组件面板    │       画布编辑区         │  属性配置区  │
│             │                         │             │
│  - 文本     │    ┌───────────────┐    │  - 样式     │
│  - 图片     │    │               │    │  - 属性     │
│  - 按钮     │    │   可拖拽组件   │    │  - 事件     │
│  - 表格     │    │               │    │  - 动画     │
│  - 图表     │    └───────────────┘    │  - 历史     │
│  - 图形     │                         │             │
└─────────────┴─────────────────────────┴─────────────┘
```

### 核心模块

| 模块 | 功能描述 |
| --- | --- |
| **组件面板** | 提供文本、图片、按钮、表格、图表、图形等可拖拽组件 |
| **画布区域** | 支持组件拖动、缩放、旋转、多选、自动对齐等交互 |
| **属性面板** | 实时编辑组件样式、属性、事件绑定，双向联动更新 |
| **版本管理** | 支持页面版本保存、恢复、删除，方便回溯历史版本 |
| **AI 助手** | 通过自然语言对话式生成页面，LLM 自主决策 |

---

## 功能特性

### 核心编辑器

| 功能 | 描述 |
| --- | --- |
| 无限画布 | 支持画布缩放，适应不同尺寸页面设计 |
| SVG 动态网格 | 提供可视化参考线，辅助组件定位 |
| 实时预览 | 编辑即所见，支持预览模式查看最终效果 |
| 自动吸附 | 组件靠近时自动对齐，提升排版效率 |
| 标线对齐 | 智能显示对齐辅助线，精确布局 |
| 撤销重做 | 命令模式双栈，支持命令合并，最多 50 步历史记录 |
| 暗黑模式 | 支持明暗主题切换 |

### 组件库

| 组件类型 | 组件名称 | 功能描述 |
| --- | --- | --- |
| **基础组件** | VText | 文本组件，支持富文本编辑、动态数据绑定 |
| | VButton | 按钮组件，支持样式自定义、事件绑定 |
| | Picture | 图片组件，支持图片翻转、圆角设置 |
| | VTable | 表格组件，支持表头加粗、斑马纹样式 |
| **图形组件** | RectShape | 矩形组件，支持边框、背景色设置（容器组件） |
| | CircleShape | 圆形组件，支持圆形/椭圆切换 |
| | LineShape | 直线组件，支持颜色、粗细调整 |
| **SVG 图形** | SVGStar | 星形组件，支持填充色、边框色设置 |
| | SVGTriangle | 三角形组件，支持自定义尺寸 |
| **高级组件** | VChart | ECharts 图表组件（vue-echarts 按需引入），支持柱状图、散点图、折线图等 |
| | Group | 组合组件（internal，不在组件面板显示），支持多组件组合/拆分 |

### 交互能力

| 功能 | 快捷键 | 描述 |
| --- | --- | --- |
| 拖拽位移 | 鼠标左键拖动 | 自由移动组件位置 |
| 八点缩放 | 拖拽控制点 | 八个方向调整组件大小 |
| 旋转控制 | 拖拽旋转手柄 | 自由旋转组件角度 |
| 多选操作 | Ctrl + 点击 | 框选或点选多个组件 |
| 图层调整 | - | 上移/下移/置顶/置底 |
| 锁定/解锁 | - | 防止误操作 |
| 复制粘贴 | Ctrl+C / Ctrl+V | 快速复制组件 |
| 删除组件 | Delete / Backspace | 删除选中组件 |

### 进阶功能

| 功能 | 描述 |
| --- | --- |
| **动画系统** | 内嵌 Animate.css 关键帧子集（74 种），支持入场/离场动画，可配置时长、延迟、循环 |
| **事件绑定** | 支持 redirect（安全跳转）和 alert（弹窗提示）事件 |
| **组件联动** | 组件间数据联动，一个组件触发另一个组件样式变化（v-click / v-hover） |
| **数据请求** | 支持配置 API 请求（GET/POST/PUT/DELETE），动态获取组件数据，支持定时轮询 |
| **右键菜单** | 提供快捷操作入口：复制、粘贴、剪切、删除、锁定、组合等 |
| **JSON 导入导出** | 一键导出页面 JSON 数据，导入时通过 Zod 运行时校验数据格式 |
| **HTML 导出** | 将画布导出为自包含独立 HTML 文件（内联样式 + 动画关键帧 + 事件绑定） |
| **版本管理** | 保存页面历史版本，支持版本恢复和删除，持久化到 localStorage |
| **命令时间线** | undo 历史可视化（CommandTimeline 组件），命令栈跨会话持久化到 IndexedDB |
| **AI 生成** | 基于 LangGraph Agent 的对话式页面生成，支持提问、选项、方案确认、生成、修改 |
| **XSS 防护** | 使用 DOMPurify 净化富文本内容，HTML 导出时对 URL/CSS 进行安全校验 |

---

## 核心设计

### 1. 页面数据结构设计

采用**扁平数组 + parentId** 作为主要数据结构描述页面与组件的层级关系（`componentData` 是一维数组，每个组件用 `parentId` 指向父组件，`null` 表示根级组件），通过 TypeScript 接口与 Zod Schema 约束组件属性与交互行为，保障系统的类型安全与可扩展性。

```typescript
// 核心类型
interface ComponentData {
  id: string
  component: string          // 组件类型名
  label: string              // 组件标签
  propValue: PropValue       // 组件属性值
  style: ComponentStyle      // 样式配置
  parentId: string | null    // 父组件 ID
  zIndex: number             // 视觉层级
  animations: Animation[]    // 动画列表
  events: Record<string, string>  // 事件配置
  isLock: boolean            // 是否锁定
  linkage: LinkageConfig     // 联动配置
}
```

**渲染原理**：Vue 通过 `<component :is="componentMap[item.component]" v-bind="item" />` 动态渲染组件，实现数据驱动视图。

### 2. 命令模式与撤销重做

将用户操作抽象为命令对象，维护撤销/重做双栈，支持命令合并与批量操作。

```typescript
class CommandManager {
  private undoStack: Command[] = []
  private redoStack: Command[] = []
  private readonly config = { maxStackSize: 50, mergeTimeWindow: 300 }

  execute(command: Command): void {
    // 300ms 内的同类操作自动合并
    const lastCommand = this.undoStack[this.undoStack.length - 1]
    if (this.shouldMerge(lastCommand, command)) {
      const merged = lastCommand!.merge(command)
      this.undoStack[this.undoStack.length - 1] = merged
      merged.execute()
      this.redoStack = []
      return
    }
    command.execute()
    this.undoStack.push(command)
    this.redoStack = []
    if (this.undoStack.length > this.config.maxStackSize) {
      this.undoStack.shift()
    }
  }
}
```

### 3. 状态管理与双向联动

基于 Pinia 实现全局状态管理，属性面板与画布状态实时双向联动：

```
点击画布组件 → 更新 curComponent → 属性面板读取 store → 修改数据 → 自动驱动画布更新
```

### 4. 拖拽系统实现

核心思想：**把鼠标位移映射成组件坐标变化**，通过 RAF 节流 + DOM 直写 transform 实现高性能拖拽。

### 5. 图层管理

统一使用数组顺序作为唯一层级依据，zIndex 始终镜像为 `index + 1`，避免双轨冲突。

---

## 技术栈

| 技术 | 版本 | 作用 |
| --- | --- | --- |
| **Vue 3** | ^3.2.47 | 核心框架，Composition API，响应式渲染组件 |
| **TypeScript** | ^5.7.0 | 类型约束 |
| **Pinia** | ^2.0.32 | 状态管理 |
| **Vue Router** | ^4.1.6 | 路由管理 |
| **Element Plus** | ^2.3.0 | UI 组件库 |
| **Vite** | ^6.1.0 | 构建工具 |
| **Zod** | ^4.3.6 | 运行时数据校验 |
| **ECharts + vue-echarts** | ^5.4.1 / ^6.5.4 | 数据可视化 |
| **Ace Editor** | ^1.12.3 | JSON 代码编辑 |
| **html-to-image** | ^1.9.0 | 页面截图 |
| **nanoid** | ^4.0.0 | ID 生成 |
| **axios** | ^1.18.1 | HTTP 请求 |
| **DOMPurify** | ^3.4.11 | XSS 防护 |
| **Vitest** | ^3.1.0 | 单元测试 |

### 后端技术栈

| 技术 | 作用 |
| --- | --- |
| **FastAPI** | REST API 框架 |
| **SQLAlchemy** | ORM 数据库 |
| **SQLite** | 本地数据库（无需额外配置） |
| **LangGraph** | AI Agent 编排 |
| **LangChain OpenAI** | LLM 调用 |

---

## 快速开始

### 环境要求

- **Node.js** >= 18.0.0
- **Python** >= 3.10
- **npm** >= 7.0.0

### 安装与运行

```bash
# 1. 安装前端依赖
cd frontend && npm install

# 2. 配置前端环境变量
cp .env.example .env.local

# 3. 启动前端开发服务器
npm run dev

# 4. 新开终端，安装后端依赖
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt

# 5. 配置后端环境变量
cp .env.example .env
# 编辑 .env 中的 JWT_SECRET 和 AI_API_KEY

# 6. 启动后端
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

访问 `http://localhost:5173` 即可开始编辑。

### 常用脚本

```bash
# 前端开发
npm run dev

# 前端构建
npm run build

# 类型检查
npm run type-check

# 单元测试
npm run test:run

# 后端启动（backend 目录下）
uvicorn main:app --reload
```

---

## 项目结构

```text
frontend/
├── src/
│   ├── api/                    # AI API 服务
│   ├── commands/                # 命令模式实现
│   │   ├── CommandManager.ts    # 命令管理器（双栈 + 合并）
│   │   ├── BaseCommand.ts       # 命令基类
│   │   ├── registry.ts          # 命令注册表
│   │   ├── MoveCommand.ts       # 移动命令（可合并）
│   │   ├── ResizeCommand.ts     # 缩放命令（可合并）
│   │   ├── RotateCommand.ts     # 旋转命令（可合并）
│   │   ├── AddComponentCommand.ts
│   │   ├── DeleteComponentCommand.ts
│   │   ├── LayerCommand.ts
│   │   ├── ComposeCommand.ts
│   │   ├── DecomposeCommand.ts
│   │   ├── PasteCommand.ts
│   │   ├── CutCommand.ts
│   │   ├── ClearCanvasCommand.ts
│   │   ├── ImportDataCommand.ts
│   │   ├── BatchCommand.ts
│   │   └── __tests__/
│   ├── components/              # 编辑器 UI
│   │   ├── Editor/              # 画布渲染引擎
│   │   │   ├── index.vue        # 画布容器
│   │   │   ├── Shape.vue        # 组件包装器（拖拽、缩放、旋转）
│   │   │   ├── NodeRenderer.vue # 递归渲染器
│   │   │   ├── PreviewNodeRenderer.vue
│   │   │   ├── MarkLine.vue     # 对齐辅助线
│   │   │   ├── Grid.vue         # SVG 网格
│   │   │   ├── Area.vue         # 框选区域
│   │   │   ├── ContextMenu.vue  # 右键菜单
│   │   │   ├── Preview.vue      # 预览 / 截图
│   │   │   └── AceEditor.vue    # JSON 编辑器
│   │   ├── Toolbar.vue          # 顶部工具栏
│   │   ├── ComponentList.vue    # 组件列表
│   │   ├── RealTimeComponentList.vue # 图层列表
│   │   ├── CanvasAttr.vue       # 画布属性
│   │   ├── AnimationList.vue
│   │   ├── AnimationSettingModal.vue
│   │   ├── EventList.vue
│   │   ├── VersionHistory.vue
│   │   ├── CommandTimeline.vue
│   │   ├── AIPanel.vue          # AI 对话面板
│   │   └── Modal.vue
│   ├── custom-component/        # 组件实现
│   │   ├── VText/ VButton/ Picture/ VTable/ VChart/
│   │   ├── RectShape/ CircleShape/ LineShape/
│   │   ├── svgs/ SVGStar/ SVGTriangle/
│   │   ├── Group/               # 组合组件
│   │   ├── common/              # 通用配置（属性、事件、联动）
│   │   ├── controls/            # 属性面板控件
│   │   ├── registry.ts          # 组件注册表
│   │   └── PropPanelRenderer.vue # 元数据驱动属性面板
│   ├── composables/             # 组合式函数
│   │   ├── useAutoSave.ts       # 自动保存
│   │   ├── useCommandActions.ts # 命令操作入口
│   │   ├── useCommandHistory.ts # 命令历史持久化
│   │   ├── useVersionManager.ts # 版本管理
│   │   ├── useDragDrop.ts       # 拖拽放置
│   │   └── usePanelToggle.ts
│   ├── store/                   # 状态管理
│   │   └── index.ts             # 主 Store
│   ├── types/                   # TypeScript 类型定义
│   ├── schemas/                 # Zod Schema 校验
│   ├── utils/                   # 工具函数
│   │   ├── style.ts             # 样式计算
│   │   ├── translate.ts         # 坐标转换
│   │   ├── exportHtml.ts        # HTML 导出引擎
│   │   ├── performance.ts       # RAF 节流、视口裁剪
│   │   ├── shortcutKey.ts       # 快捷键
│   │   ├── sanitize.ts          # XSS 净化
│   │   ├── validation.ts        # Zod 校验工具
│   │   └── api.ts               # 后端 API 交互
│   ├── views/                   # 页面
│   │   ├── Home.vue             # 编辑器主页面
│   │   └── PreviewPage.vue      # 预览页
│   └── router/                  # 路由配置
├── .env.example
└── package.json

backend/                        # Python FastAPI 后端
├── app/
│   ├── models/                 # SQLAlchemy ORM 模型
│   │   ├── user.py
│   │   └── page.py
│   ├── schemas/                # Pydantic 数据校验
│   │   ├── auth.py
│   │   ├── page.py
│   │   └── ai.py
│   ├── routers/                # API 路由
│   │   ├── auth.py             # 注册/登录（保留但前端不强制使用）
│   │   ├── pages.py            # 页面 CRUD（无认证）
│   │   └── ai.py               # AI 对话接口
│   ├── middleware/              # JWT 中间件
│   ├── services/               # 业务逻辑
│   │   └── ai_service.py       # LangGraph AI Agent
│   ├── utils/                  # 工具函数
│   │   └── id_generator.py
│   ├── config.py               # 配置
│   └── database.py             # 数据库引擎
├── main.py                     # 入口
├── requirements.txt
└── .env.example
```

---

## 核心设计模式

### 命令模式（Command Pattern）

每个用户操作封装为一个命令对象，实现 `execute()` / `undo()` / `redo()` / `serialize()` 接口。支持 300ms 内同类命令合并（如拖拽、缩放、旋转），避免高频操作撑爆撤销栈。

### 组件注册表（Registry Pattern）

所有组件通过 `registerComponent()` 统一注册，元数据驱动属性面板自动渲染。新增组件只需编写 Vue 组件 + 调用注册函数，无需修改编辑器核心代码。

### 数据驱动渲染

编辑器不操作 DOM，所有交互修改 `componentData` JSON 数据，Vue 响应式系统自动驱动画布更新。一份数据贯穿编辑、预览、保存、导入导出全流程。

---

## 扩展开发

### 添加新组件

1. 在 `src/custom-component/` 下创建组件目录（含 `Component.vue` 和可选的 `Attr.vue`）
2. 在 `src/custom-component/component-list.ts` 中添加组件模板
3. 在 `src/custom-component/index.ts` 中调用 `registerComponent()` 注册

### 组件开发示例

```vue
<!-- Component.vue -->
<template>
  <div class="my-component" :style="style">{{ propValue }}</div>
</template>
<script setup lang="ts">
const props = defineProps<{ propValue: string; style: Record<string, any> }>()
</script>
```

```typescript
// index.ts 注册
registerComponent('MyComponent', MyComp, {
  type: 'MyComponent', label: '我的组件', icon: 'myicon',
  propConfigs: [
    { key: 'propValue', label: '文字内容', type: 'textarea' },
    { key: 'style.color', label: '文字颜色', type: 'color' },
  ],
})
```

---

## License

MIT