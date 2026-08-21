<template>
    <div ref="containerRef" class="layout-container" :class="{ 'has-children': hasChildren }">
        <!-- 顶部 header 固定区域 -->
        <div
            class="layout-region layout-header"
            data-slot="header"
            :style="{ height: `${headerHeight}px` }"
        >
            <slot name="header" />
        </div>
        <!-- 中间 default 自由区域 -->
        <div class="layout-region layout-body" data-slot="default">
            <slot name="default" />
        </div>
        <!-- 底部 footer 固定区域 -->
        <div
            class="layout-region layout-footer"
            data-slot="footer"
            :style="{ height: `${footerHeight}px` }"
        >
            <slot name="footer" />
        </div>
    </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useStore } from '@/store'
import { useOnEvent } from '../common/useOnEvent'
import type { ComponentData, LinkageConfig, LayoutContainerPropValue } from '@/types'

interface Props {
  propValue: LayoutContainerPropValue
  element: ComponentData
  linkage: LinkageConfig
}

const props = defineProps<Props>()

const store = useStore()
const containerRef = ref<HTMLElement | null>(null)

// 顶部/底部固定区域高度（属性面板可调，缺省 48px）
const headerHeight = computed(() => props.propValue?.headerHeight ?? 48)
const footerHeight = computed(() => props.propValue?.footerHeight ?? 48)

// 是否有子组件（用于空区域占位样式）
const hasChildren = computed(() => {
    return store.componentData.some(c => c.parentId === props.element.id)
})

useOnEvent(props, containerRef)
</script>

<style lang="scss" scoped>
.layout-container {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;

  .layout-region {
    position: relative; /* 为区域内绝对定位的子组件提供定位上下文 */
    flex-shrink: 0;
  }

  .layout-header {
    background-color: rgba(64, 158, 255, 0.06);
    border-bottom: 1px dashed #dcdfe6;
  }

  .layout-body {
    flex: 1;
    min-height: 0;
  }

  .layout-footer {
    background-color: rgba(64, 158, 255, 0.06);
    border-top: 1px dashed #dcdfe6;
  }
}
</style>
