<template>
    <Shape
        :default-style="node.style"
        :style="{ ...getShapeStyle(node.style), zIndex: node.zIndex }"
        :active="node.id === curComponent?.id"
        :element="node"
        :index="index"
        :class="{ lock: node.isLock }"
    >
        <!-- SVG 组件 -->
        <component
            :is="node.component"
            v-if="node.component.startsWith('SVG')"
            :id="'component' + node.id"
            :style="getSVGStyle(node.style)"
            class="component"
            :prop-value="node.propValue"
            :element="node"
            :request="node.request"
            :linkage="node.linkage"
        >
            <!-- 子组件按插槽区域分发（header / default / footer） -->
            <template v-for="(group, slotName) in slotGroups" :key="slotName" #[slotName]>
                <NodeRenderer
                    v-for="child in group"
                    :key="child.id"
                    :node="child"
                    :index="getIndex(child.id)"
                />
            </template>
        </component>

        <!-- 非 VText 组件（含容器） -->
        <component
            :is="node.component"
            v-else-if="node.component !== 'VText'"
            :id="'component' + node.id"
            class="component"
            :style="getComponentStyle(node.style)"
            :prop-value="node.propValue"
            :element="node"
            :request="node.request"
            :linkage="node.linkage"
        >
            <!-- 子组件按插槽区域分发（header / default / footer） -->
            <template v-for="(group, slotName) in slotGroups" :key="slotName" #[slotName]>
                <NodeRenderer
                    v-for="child in group"
                    :key="child.id"
                    :node="child"
                    :index="getIndex(child.id)"
                />
            </template>
        </component>

        <!-- VText 组件（带 input 事件） -->
        <component
            :is="node.component"
            v-else
            :id="'component' + node.id"
            class="component"
            :style="getComponentStyle(node.style)"
            :prop-value="node.propValue"
            :element="node"
            :request="node.request"
            :linkage="node.linkage"
            @input="handleInput"
        />
    </Shape>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useStore } from '@/store'
import { storeToRefs } from 'pinia'
import Shape from './Shape.vue'
import {
    getShapeStyle as getShapeStyleUtils,
    getSVGStyle as getSVGStyleUtils,
    getStyle,
} from '@/utils/style'
import type { ComponentData, ComponentStyle } from '@/types'

interface Props {
  node: ComponentData
  index: number
}

const props = defineProps<Props>()

const store = useStore()
const { curComponent, canvasStyleData } = storeToRefs(store)
const svgFilterAttrs: (keyof ComponentStyle)[] = ['width', 'height', 'top', 'left', 'rotate']

/**
 * 查找当前组件的所有子组件（parentId 等于当前节点 id）
 * 通过 store.childrenIndex 实现 O(1) 查询，替代 O(n) filter
 */
const children = computed<ComponentData[]>(() => {
    return store.childrenIndex.get(props.node.id) ?? []
})

/**
 * 子组件按 slot 字段分组，分发到容器的对应插槽区域
 * （未声明插槽的容器子组件统一归入 default 插槽，与旧行为一致）
 */
const slotGroups = computed<Record<string, ComponentData[]>>(() => {
    const groups: Record<string, ComponentData[]> = {}
    for (const child of children.value) {
        const name = child.slot || 'default'
        ;(groups[name] ??= []).push(child)
    }
    return groups
})

/**
 * 获取组件在扁平数组中的索引（用于选中状态同步）
 * 通过 componentIndexMap（Editor/index.vue 层已提供）实现 O(1) 查找
 */
function getIndex(id: string): number {
    return store.componentData.findIndex(c => c.id === id)
}

function getShapeStyle(style: ComponentStyle): Record<string, string | number> {
    return getShapeStyleUtils(style)
}

function getComponentStyle(style: ComponentStyle): Record<string, string | number> {
    return getStyle(style, svgFilterAttrs)
}

function getSVGStyle(style: ComponentStyle): Record<string, string | number> {
    return getSVGStyleUtils(style, svgFilterAttrs)
}

function handleInput(element: ComponentData, value: string): void {
    store.setShapeStyle({ height: getTextareaHeight(element, value) })
}

function getTextareaHeight(element: ComponentData, text: string): number {
    const { fontSize, height, lineHeight: rawLineHeight } = element.style
    const lineHeight = rawLineHeight ? parseFloat(rawLineHeight) : 1.5

    const newHeight =
    (text.split('<br>').length - 1) * lineHeight * (fontSize || canvasStyleData.value.fontSize)
    return height > newHeight ? height : newHeight
}
</script>
