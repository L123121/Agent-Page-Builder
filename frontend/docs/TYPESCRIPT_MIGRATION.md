# TypeScript 迁移文档

## 概述

本文档记录了项目从 JavaScript 到 TypeScript 的完整迁移过程。项目已完成全面迁移，所有核心文件均已使用 TypeScript 重写。

---

## 迁移状态

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 类型定义 (`src/types/`) | ✅ 完成 | 完整的类型系统 |
| 工具函数 (`src/utils/`) | ✅ 完成 | 所有工具函数已迁移 |
| 状态管理 (`src/store/`) | ✅ 完成 | Pinia Store 完整类型支持 |
| 组件模板 (`src/custom-component/`) | ✅ 完成 | 组件列表和注册 |
| Vue 组件 | ✅ 完成 | 使用 `<script setup lang="ts">` |
| 配置文件 | ✅ 完成 | vite.config.ts, tsconfig.json |

---

## 类型系统

### 核心类型定义

项目在 `src/types/index.ts` 中定义了完整的类型系统：

```typescript
// ==================== 基础样式 ====================
export interface ComponentStyle {
  width: number
  height: number
  top?: number
  left?: number
  rotate?: number
  opacity?: number
  fontSize?: number
  fontWeight?: number
  lineHeight?: string
  letterSpacing?: number
  textAlign?: 'left' | 'center' | 'right'
  color?: string
  backgroundColor?: string
  borderColor?: string
  borderWidth?: number
  borderStyle?: 'solid' | 'dashed' | 'dotted'
  borderRadius?: string
  padding?: number
  verticalAlign?: 'top' | 'middle' | 'bottom'
}

// ==================== 请求配置 ====================
export interface RequestConfig {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE'
  data: Record<string, unknown>[]
  url: string
  series: boolean      // 是否定时发送请求
  time: number         // 定时更新时间(ms)
  paramType: '' | 'string' | 'object' | 'array'
  requestCount: number // 请求次数限制，0 为无限
}

// ==================== 动画配置 ====================
export interface Animation {
  type: string
  duration: number
  delay: number
  interationNum: number
  infinite: boolean
  applyTo: 'enter' | 'leave'
}

// ==================== 组件联动 ====================
export interface LinkageItem {
  id: string
  label: string
  event: string
  style: Array<{ key: string; value: string }>
}

export interface LinkageConfig {
  duration: number
  data: LinkageItem[]
}

// ==================== 组件数据 ====================
export type PropValue = string | PicturePropValue | TablePropValue | ChartPropValue | ComponentData[]

export interface ComponentData {
  id: string
  component: string
  label: string
  icon: string
  propValue: PropValue
  style: ComponentStyle
  request?: RequestConfig
  animations: Animation[]
  events: Record<string, string>
  groupStyle: Record<string, unknown>
  isLock: boolean
  collapseName: string
  linkage: LinkageConfig
}

// ==================== Store 状态 ====================
export interface StoreState {
  editMode: 'edit' | 'preview'
  canvasStyleData: CanvasStyleData
  componentData: ComponentData[]
  curComponent: ComponentData | null
  curComponentIndex: number | null
  isClickComponent: boolean
  editor: HTMLElement | null
  snapshotData: ComponentData[][]
  snapshotIndex: number
  menuTop: number
  menuLeft: number
  menuShow: boolean
  copyData: CopyData | null
  isDarkMode: boolean
  rightList: boolean
  isInEditor: boolean
  areaData: AreaData
  versions: PageVersion[]
}

// ==================== 版本管理 ====================
export interface PageVersion {
  id: string
  name: string
  description: string
  snapshot: ComponentData[]
  createdAt: string
  thumbnail?: string
}
```

---

## 配置文件

### tsconfig.json

```json
{
  "compilerOptions": {
    "target": "ESNext",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "jsx": "preserve",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "esModuleInterop": true,
    "lib": ["ESNext", "DOM"],
    "skipLibCheck": true,
    "noEmit": true,
    "paths": {
      "@/*": ["./src/*"]
    },
    "baseUrl": ".",
    "allowJs": true,
    "checkJs": false
  },
  "include": ["src/**/*.ts", "src/**/*.d.ts", "src/**/*.tsx", "src/**/*.vue"],
  "exclude": ["node_modules"]
}
```

### env.d.ts

```typescript
/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

// Element Plus 类型
declare module 'element-plus'
```

---

## Vue 组件开发规范

### 使用 `<script setup lang="ts">`

```vue
<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import type { ComponentData } from '@/types'
import { useStore } from '@/store'

const store = useStore()

// Props 类型定义
interface Props {
  component: ComponentData
  index: number
}

const props = defineProps<Props>()

// 带默认值的 Props
interface PropsWithDefaults {
  title: string
  count?: number
}

const props = withDefaults(defineProps<PropsWithDefaults>(), {
  count: 0
})

// Emits 类型定义
const emit = defineEmits<{
  (e: 'select', id: string): void
  (e: 'delete', index: number): void
  (e: 'update', data: Partial<ComponentData>): void
}>()

// 响应式状态
const isActive = computed(() => store.curComponent?.id === props.component.id)
const localState = ref<string>('')

// 方法
const handleClick = (): void => {
  emit('select', props.component.id)
}

// 生命周期
onMounted(() => {
  // 初始化逻辑
})

onUnmounted(() => {
  // 清理逻辑
})
</script>
```

### 组件属性面板开发

```vue
<template>
  <div class="attr-panel">
    <el-form :model="formData" label-width="80px">
      <el-form-item label="宽度">
        <el-input-number v-model="formData.width" :min="0" />
      </el-form-item>
      <el-form-item label="高度">
        <el-input-number v-model="formData.height" :min="0" />
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useStore } from '@/store'
import type { ComponentStyle } from '@/types'

const store = useStore()

const formData = computed({
  get: () => ({
    width: store.curComponent?.style.width ?? 0,
    height: store.curComponent?.style.height ?? 0
  }),
  set: (val) => {
    if (store.curComponent) {
      store.setShapeStyle({
        width: val.width,
        height: val.height
      })
    }
  }
})

// 监听组件变化
watch(
  () => store.curComponent,
  (newVal) => {
    if (newVal) {
      // 更新表单数据
    }
  },
  { deep: true }
)
</script>
```

---

## Store 开发规范

### Pinia Store 类型定义

```typescript
import { defineStore } from 'pinia'
import type { StoreState, ComponentData } from '@/types'

export const useStore = defineStore('main', {
  state: (): StoreState => ({
    editMode: 'edit',
    componentData: [],
    curComponent: null,
    // ...
  }),

  getters: {
    // 带类型的 getter
    componentCount: (state): number => state.componentData.length,
    
    // 返回可能为空的 getter
    currentStyle: (state): ComponentStyle | null => {
      return state.curComponent?.style ?? null
    }
  },

  actions: {
    // 带类型的 action
    setCurComponent({ component, index }: { component: ComponentData; index: number }): void {
      this.curComponent = component
      this.curComponentIndex = index
    },

    // 异步 action
    async fetchData(url: string): Promise<void> {
      try {
        const response = await fetch(url)
        const data = await response.json()
        // 处理数据
      } catch (error) {
        console.error('Fetch error:', error)
      }
    }
  }
})
```

---

## 工具函数开发规范

### 类型安全的工具函数

```typescript
// src/utils/utils.ts

/**
 * 深拷贝函数
 */
export function deepCopy<T>(target: T): T {
  if (target === null || typeof target !== 'object') {
    return target
  }

  try {
    return structuredClone(target)
  } catch {
    if (Array.isArray(target)) {
      return target.map(item => deepCopy(item)) as T
    }

    const result = {} as T
    for (const key in target) {
      if (Object.prototype.hasOwnProperty.call(target, key)) {
        result[key] = deepCopy(target[key])
      }
    }
    return result
  }
}

/**
 * 交换数组元素
 */
export function swap<T>(arr: T[], i: number, j: number): void {
  const temp = arr[i]
  arr[i] = arr[j]
  arr[j] = temp
}

/**
 * DOM 选择器（泛型支持）
 */
export function $<T extends Element = Element>(selector: string): T | null {
  return document.querySelector<T>(selector)
}

/**
 * 判断组件是否阻止拖放
 */
export function isPreventDrop(component: string): boolean {
  const preventComponents = ['VText', 'RectShape', 'CircleShape'] as const
  return !preventComponents.includes(component as typeof preventComponents[number]) 
    && !component.startsWith('SVG')
}
```

---

## 常见问题

### Q: JS 和 TS 可以共存吗？

A: 可以。`allowJs: true` 配置允许在 TS 项目中导入 JS 文件。但建议逐步迁移所有文件。

### Q: 如何处理第三方库没有类型？

A: 在 `src/env.d.ts` 中声明模块：

```typescript
declare module 'some-library'
```

或安装 `@types/some-library`。

### Q: Vue 组件 props 如何定义类型？

A: 使用 `defineProps<T>()` 或 `withDefaults(defineProps<T>(), defaults)`：

```typescript
// 基础用法
const props = defineProps<{ title: string }>()

// 带默认值
const props = withDefaults(
  defineProps<{ title: string; count?: number }>(),
  { count: 0 }
)
```

### Q: 如何处理复杂类型？

A: 在 `src/types/index.ts` 中定义，然后导入使用：

```typescript
import type { ComponentData, Animation } from '@/types'
```

### Q: 类型检查报错但代码能运行？

A: 检查以下几点：
1. 确保类型定义完整
2. 使用类型断言 `as` 谨慎处理
3. 检查第三方库是否有类型声明

---

## 类型检查命令

```bash
# 运行类型检查
npm run type-check

# 构建时自动检查
npm run build
```

---

## 最佳实践

1. **优先使用类型导入**：`import type { X } from 'module'`
2. **避免 `any`**：使用 `unknown` 或具体类型
3. **使用枚举**：对于有限的值集合，使用 `enum` 或联合类型
4. **保持类型同步**：修改代码时同步更新类型定义
5. **利用 IDE 提示**：VSCode + Volar 提供完整的类型提示

---

## 迁移收益

| 方面 | 迁移前 | 迁移后 |
| --- | --- | --- |
| 类型安全 | 无 | 编译时类型检查 |
| IDE 支持 | 基础提示 | 完整智能提示 |
| 重构能力 | 手动查找 | 自动重构 |
| 文档化 | 需要额外注释 | 类型即文档 |
| Bug 发现 | 运行时 | 编译时 |

---

## 相关资源

- [Vue 3 + TypeScript 官方文档](https://vuejs.org/guide/typescript/overview.html)
- [Pinia TypeScript 支持](https://pinia.vuejs.org/core-concepts/#typescript)
- [TypeScript 官方文档](https://www.typescriptlang.org/docs/)
