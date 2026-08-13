/**
 * HTML 导出引擎
 *
 * 将画布组件数据（componentData）转换为自包含的独立 HTML 文件。
 * 导出的 HTML 无需任何外部依赖，双击即可在浏览器中打开。
 *
 * 功能：
 * - 所有组件样式内联（position: absolute 布局）
 * - 事件绑定（跳转链接、弹窗提示）
 * - 动画支持（内嵌 animate.css 关键帧）
 * - 嵌套组件（parentId 递归渲染）
 * - 图片资源以 URL 形式引用
 */

import type { ComponentData, CanvasStyleData } from '@/types'
import { isValidCssColor } from '@/utils/sanitize'
import { renderComponent } from './renderers'
import { ANIMATION_KEYFRAMES } from './keyframes'

export interface ExportHtmlOptions {
  title?: string
  componentData: ComponentData[]
  canvasStyle: CanvasStyleData
}

/**
 * 导出为独立 HTML 文件
 * @returns HTML 字符串
 */
export function exportToHtml({ title = '低代码页面', componentData, canvasStyle }: ExportHtmlOptions): string {
    const rootComponents = componentData.filter(c => !c.parentId)
    const canvasWidth = canvasStyle.width || 1200
    const canvasHeight = canvasStyle.height || 740
    const bgColor = isValidCssColor(canvasStyle.backgroundColor || '') ? canvasStyle.backgroundColor : '#fff'

    // 渲染所有根组件
    const componentsHtml = rootComponents
        .map(component => renderComponent({ component, allComponents: componentData }))
        .join('\n    ')

    // 构建完整 HTML
    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${title}</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  min-height: 100vh;
  background: #f0f0f0;
  padding: 40px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
.page-container {
  position: relative;
  background: ${bgColor};
  box-shadow: 0 4px 20px rgba(0,0,0,0.08);
  border-radius: 4px;
  overflow: hidden;
  flex-shrink: 0;
}
${ANIMATION_KEYFRAMES}
</style>
</head>
<body>
<div class="page-container" style="width:${canvasWidth}px;height:${canvasHeight}px;">
  ${componentsHtml}
</div>
<script>
// 页面加载完成后执行进入动画
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.animated').forEach(function(el) {
    var time = el.style.getPropertyValue('--animate-time') || '1s';
    el.style.animationDuration = time;
  });

  // 委托事件处理（安全方式，避免内联 JS 注入）
  document.addEventListener('click', function(e) {
    var el = e.target.closest('[data-event-type]');
    if (!el) return;
    var type = el.getAttribute('data-event-type');
    var param = el.getAttribute('data-event-param');
    if (type === 'redirect' && /^https?:\\/\\//.test(param)) {
      window.open(param, '_blank', 'noopener,noreferrer');
    } else if (type === 'alert') {
      window.alert(param);
    }
  });
});
<\/script>
</body>
</html>`
}

/**
 * 下载 HTML 文件
 */
export function downloadHtmlFile(html: string, filename: string = 'page.html'): void {
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.setAttribute('download', filename)
    a.href = url
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
}
