/**
 * 组件渲染器 — 将各类型组件转为 HTML 字符串
 * 用于 HTML 导出
 */
import type { ComponentData, Animation } from '@/types'
import { escapeHtml, isValidImageUrl, isValidCssColor } from '@/utils/sanitize'
import { styleToInline } from './styleToInline'

// ==================== 渲染上下文 ====================

export interface RenderContext {
  component: ComponentData
  allComponents: ComponentData[]
}

// ==================== 辅助函数 ====================

/**
 * 生成动画的 HTML 属性
 */
function getAnimationAttributes(animations: Animation[]): string {
    if (!animations || animations.length === 0) return ''

    // 只取第一个动画用于进入效果
    const enterAnim = animations.find(a => a.applyTo === 'enter' || !a.applyTo) || animations[0]
    if (!enterAnim) return ''

    const classes = ['animated', enterAnim.type]
    if (enterAnim.infinite) classes.push('infinite')

    const style = `--animate-time: ${enterAnim.duration / 1000}s; animation-delay: ${enterAnim.delay}ms;`
    return `class="${classes.join(' ')}" style="${style}"`
}

function buildEventAttribute(events: Record<string, string>): string {
    const entries = Object.entries(events)
    if (entries.length === 0) return ''

    // 只处理第一个事件，使用 data 属性存储（避免内联 JS 注入）
    const [type, param] = entries[0]
    return `data-event-type="${escapeHtml(type)}" data-event-param="${escapeHtml(param)}"`
}

/**
 * 渲染子组件（通过 parentId 查找）
 */
function renderChildren(ctx: RenderContext): string {
    const { component, allComponents } = ctx
    const children = allComponents.filter(c => c.parentId === component.id)
    if (children.length === 0) return ''

    return children.map(child => renderComponent({ component: child, allComponents })).join('\n')
}

// ==================== 各类型组件渲染 ====================

function renderVText(ctx: RenderContext): string {
    const { component } = ctx
    const text = component.propValue as string || ''
    const style = styleToInline(component.style)
    const animAttr = getAnimationAttributes(component.animations)
    const escapedText = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>')

    return `<div ${animAttr} style="position:absolute; ${style}">${escapedText}</div>`
}

function renderVButton(ctx: RenderContext): string {
    const { component } = ctx
    const text = component.propValue as string || ''
    const style = styleToInline(component.style)
    const animAttr = getAnimationAttributes(component.animations)
    const escapedText = escapeHtml(text)
    const eventData = buildEventAttribute(component.events)

    return `<div ${animAttr} style="position:absolute; display:flex; align-items:center; justify-content:center; ${style}; cursor:pointer" ${eventData}>${escapedText}</div>`
}

function renderPicture(ctx: RenderContext): string {
    const { component } = ctx
    const propValue = component.propValue as { url?: string; flip?: { horizontal?: boolean; vertical?: boolean } } || {}
    const style = styleToInline(component.style)
    const imgUrl = propValue.url || ''
    const safeUrl = isValidImageUrl(imgUrl) ? escapeHtml(imgUrl) : ''
    const flipTransform: string[] = []
    if (propValue.flip?.horizontal) flipTransform.push('scaleX(-1)')
    if (propValue.flip?.vertical) flipTransform.push('scaleY(-1)')
    const imgStyle = flipTransform.length ? `transform: ${flipTransform.join(' ')}` : ''
    const animAttr = getAnimationAttributes(component.animations)

    return `<div ${animAttr} style="position:absolute; ${style}"><img src="${safeUrl}" style="width:100%;height:100%;object-fit:fill;${imgStyle}" /></div>`
}

function renderRectShape(ctx: RenderContext): string {
    const { component } = ctx
    const text = component.propValue as string || ''
    const baseStyle = styleToInline(component.style)
    const style = `position:absolute; overflow:hidden; ${baseStyle}`
    const animAttr = getAnimationAttributes(component.animations)
    const childrenHtml = renderChildren(ctx)
    const escapedText = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

    return `<div ${animAttr} style="${style}"><div style="padding:4px;">${escapedText}</div>${childrenHtml}</div>`
}

function renderCircleShape(ctx: RenderContext): string {
    const { component } = ctx
    const text = component.propValue as string || ''
    const baseStyle = styleToInline(component.style)
    const style = `position:absolute; display:flex; align-items:center; justify-content:center; overflow:hidden; ${baseStyle}`
    const animAttr = getAnimationAttributes(component.animations)
    const escapedText = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

    return `<div ${animAttr} style="${style}"><span>${escapedText}</span></div>`
}

function renderLineShape(ctx: RenderContext): string {
    const { component } = ctx
    const baseStyle = styleToInline(component.style)
    const animAttr = getAnimationAttributes(component.animations)

    return `<div ${animAttr} style="position:absolute; ${baseStyle}"></div>`
}

function renderSVGStar(ctx: RenderContext): string {
    const { component } = ctx
    const style = component.style
    const w = style.width || 80
    const h = style.height || 80
    const fill = style.color || '#000'
    const bg = style.backgroundColor || 'transparent'
    const animAttr = getAnimationAttributes(component.animations)

    return `<div ${animAttr} style="position:absolute; left:${style.left ?? 0}px; top:${style.top ?? 0}px; width:${w}px; height:${h}px; background:${bg};">
    <svg viewBox="0 0 24 24" width="${w}" height="${h}" fill="${fill}">
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
    </svg>
  </div>`
}

function renderSVGTriangle(ctx: RenderContext): string {
    const { component } = ctx
    const style = component.style
    const w = style.width || 80
    const h = style.height || 80
    const fill = style.color || '#000'
    const bg = style.backgroundColor || 'transparent'
    const animAttr = getAnimationAttributes(component.animations)

    return `<div ${animAttr} style="position:absolute; left:${style.left ?? 0}px; top:${style.top ?? 0}px; width:${w}px; height:${h}px; background:${bg};">
    <svg viewBox="0 0 24 24" width="${w}" height="${h}" fill="${fill}">
      <path d="M12 2L2 22h20L12 2z"/>
    </svg>
  </div>`
}

function renderVTable(ctx: RenderContext): string {
    const { component } = ctx
    const style = styleToInline(component.style)
    const propValue = component.propValue as { data?: string[][]; stripe?: boolean; thBold?: boolean } || {}
    const data = propValue.data || []
    const animAttr = getAnimationAttributes(component.animations)

    if (data.length === 0) {
        return `<div style="position:absolute; display:flex; align-items:center; justify-content:center; ${style}">空表格</div>`
    }

    const headerRow = data[0] || []
    const bodyRows = data.slice(1)
    const headers = headerRow.map((h: string) => `<th style="border:1px solid #d9d9d9;padding:4px 8px;${propValue.thBold ? 'font-weight:bold' : ''}">${escapeHtml(h)}</th>`).join('')
    const rows = bodyRows.map((row: string[]) => {
        const cells = row.map((cell: string) => `<td style="border:1px solid #d9d9d9;padding:4px 8px;">${escapeHtml(cell)}</td>`).join('')
        return `<tr>${cells}</tr>`
    }).join('')

    const tableStyle = propValue.stripe ? 'border-collapse:collapse;width:100%;height:100%;' : 'border-collapse:collapse;width:100%;height:100%;'

    return `<div ${animAttr} style="position:absolute; overflow:auto; ${style}"><table style="${tableStyle}"><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table></div>`
}

function renderVChart(ctx: RenderContext): string {
    const { component } = ctx
    const style = styleToInline(component.style)
    const animAttr = getAnimationAttributes(component.animations)

    return `<div ${animAttr} style="position:absolute; display:flex; align-items:center; justify-content:center; background:#f5f5f5; color:#999; font-size:14px; ${style}"><div style="text-align:center;"><div>📊 图表</div><div style="font-size:12px;margin-top:4px;">导出 HTML 暂不支持动态图表</div></div></div>`
}

function renderGroup(ctx: RenderContext): string {
    const { component } = ctx
    const style = styleToInline(component.style)
    const children = component.propValue as ComponentData[]

    let childrenHtml = ''
    if (Array.isArray(children)) {
        childrenHtml = children.map(child => renderComponent({ component: child, allComponents: ctx.allComponents })).join('\n')
    }

    return `<div style="position:absolute; ${style}">${childrenHtml}</div>`
}

// ==================== 渲染分发 ====================

type Renderer = (ctx: RenderContext) => string

const RENDERERS: Record<string, Renderer> = {
    VText: renderVText,
    VButton: renderVButton,
    Picture: renderPicture,
    RectShape: renderRectShape,
    CircleShape: renderCircleShape,
    LineShape: renderLineShape,
    SVGStar: renderSVGStar,
    SVGTriangle: renderSVGTriangle,
    VTable: renderVTable,
    VChart: renderVChart,
    Group: renderGroup,
}

/**
 * 渲染单个组件（按类型分发）
 */
export function renderComponent(ctx: RenderContext): string {
    const renderer = RENDERERS[ctx.component.component]
    if (!renderer) {
        // 未知组件，渲染为空白占位
        const style = styleToInline(ctx.component.style)
        return `<div style="position:absolute; display:flex; align-items:center; justify-content:center; background:#eee; color:#999; font-size:12px; ${style}">${ctx.component.component}</div>`
    }
    return renderer(ctx)
}
