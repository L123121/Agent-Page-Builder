/**
 * 样式转换工具 — 将组件样式对象转为内联 CSS 字符串
 * 用于 HTML 导出
 */
import type { ComponentStyle } from '@/types'

/** 将组件样式对象转为内联 style 字符串 */
export function styleToInline(style: ComponentStyle): string {
    const styleMap: Record<string, string> = {
        width: 'width',
        height: 'height',
        top: 'top',
        left: 'left',
        rotate: 'transform',
        opacity: 'opacity',
        fontSize: 'font-size',
        fontWeight: 'font-weight',
        lineHeight: 'line-height',
        letterSpacing: 'letter-spacing',
        textAlign: 'text-align',
        color: 'color',
        backgroundColor: 'background-color',
        borderColor: 'border-color',
        borderWidth: 'border-width',
        borderStyle: 'border-style',
        borderRadius: 'border-radius',
        padding: 'padding',
        verticalAlign: 'vertical-align',
    }

    const lines: string[] = []
    let transformStr = ''

    for (const [key, value] of Object.entries(style)) {
        if (value === undefined || value === null || value === '') continue
        const cssKey = styleMap[key]
        if (!cssKey) continue

        if (key === 'rotate') {
            transformStr = `rotate(${value}deg)`
            continue
        }

        const needsPx = ['width', 'height', 'top', 'left', 'fontSize', 'borderWidth', 'letterSpacing', 'borderRadius', 'padding'].includes(key)
        // borderRadius can be a string like '50%', don't add px if it already has a unit
        if (needsPx && key === 'borderRadius' && typeof value === 'string' && /%|px|em|rem/.test(value)) {
            lines.push(`${cssKey}: ${value}`)
        } else if (needsPx && typeof value === 'number') {
            lines.push(`${cssKey}: ${value}px`)
        } else {
            lines.push(`${cssKey}: ${value}`)
        }
    }

    if (transformStr) {
        lines.push(`transform: ${transformStr}`)
    }

    return lines.join('; ')
}
