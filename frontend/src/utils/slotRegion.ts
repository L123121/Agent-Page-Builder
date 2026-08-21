import type { ComponentData, LayoutContainerPropValue } from '@/types'

/** 布局容器组件类型名 */
export const LAYOUT_CONTAINER_TYPE = 'LayoutContainer'
/** 插槽区域名称 */
export const LAYOUT_SLOT_HEADER = 'header'
export const LAYOUT_SLOT_DEFAULT = 'default'
export const LAYOUT_SLOT_FOOTER = 'footer'
/** 区域高度缺省值（px） */
export const DEFAULT_SLOT_HEIGHT = 48

export interface LayoutSlotHeights {
  headerHeight: number
  footerHeight: number
}

/**
 * 读取布局容器的区域高度配置（带缺省值兜底）
 */
export function getLayoutSlotHeights(container: ComponentData): LayoutSlotHeights {
  const pv = container.propValue as Partial<LayoutContainerPropValue> | null | undefined
  return {
    headerHeight: pv?.headerHeight ?? DEFAULT_SLOT_HEIGHT,
    footerHeight: pv?.footerHeight ?? DEFAULT_SLOT_HEIGHT,
  }
}

/**
 * 判断组件是否为多插槽布局容器
 */
export function isLayoutContainer(component: ComponentData): boolean {
  return component.component === LAYOUT_CONTAINER_TYPE
}

/**
 * 根据落点（画布坐标系）判断命中容器的哪个插槽区域。
 * 区域边界由容器尺寸与 header/footer 高度计算：
 *   header  = [容器顶, 容器顶 + headerHeight)
 *   footer  = [容器底 - footerHeight, 容器底)
 *   default = 中间剩余区域
 */
export function resolveDropSlot(container: ComponentData, dropX: number, dropY: number): string {
  if (!isLayoutContainer(container)) return LAYOUT_SLOT_DEFAULT
  const { headerHeight, footerHeight } = getLayoutSlotHeights(container)
  const relY = dropY - (container.style.top ?? 0)
  const height = container.style.height ?? 0
  if (relY < headerHeight) return LAYOUT_SLOT_HEADER
  if (relY >= height - footerHeight) return LAYOUT_SLOT_FOOTER
  return LAYOUT_SLOT_DEFAULT
}

/**
 * 插槽区域相对容器顶部的偏移。
 * 用于把落点的容器相对坐标换算为区域相对坐标（子组件 top/left 以区域为基准）。
 */
export function getSlotRegionOffsetTop(container: ComponentData, slot: string): number {
  if (!isLayoutContainer(container) || slot === LAYOUT_SLOT_HEADER) return 0
  const { headerHeight, footerHeight } = getLayoutSlotHeights(container)
  if (slot === LAYOUT_SLOT_FOOTER) {
    return Math.max((container.style.height ?? 0) - footerHeight, headerHeight)
  }
  return headerHeight
}
