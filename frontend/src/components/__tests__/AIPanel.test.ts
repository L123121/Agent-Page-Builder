import { describe, it, expect, beforeEach } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import AIPanelHost from './AIPanelHost.vue'

function mountHost() {
    const el = document.createElement('div')
    document.body.appendChild(el)
    const app = createApp(AIPanelHost)
    app.use(createPinia())
    const vm = app.mount(el)
    return { el, app, vm }
}

describe('AIPanel v-model 弹出链路', () => {
    beforeEach(() => {
        localStorage.clear()
        document.body.innerHTML = ''
    })

    it('初始状态面板不可见（无 visible 类）', () => {
        const { el } = mountHost()
        const panel = el.querySelector('.ai-panel') as HTMLElement
        expect(panel).toBeTruthy()
        expect(panel.className).not.toContain('visible')
    })

    it('点击 AI 按钮后面板获得 visible 类', async () => {
        const { el } = mountHost()
        const btn = el.querySelector('#ai-toggle-btn') as HTMLButtonElement
        expect(btn).toBeTruthy()

        btn.click()
        await nextTick()
        await nextTick()

        const panel = el.querySelector('.ai-panel') as HTMLElement
        expect(panel.className).toContain('visible')
    })

    it('再次点击后面板收起（visible 类移除）', async () => {
        const { el } = mountHost()
        const btn = el.querySelector('#ai-toggle-btn') as HTMLButtonElement
        const panel = el.querySelector('.ai-panel') as HTMLElement

        btn.click()
        await nextTick()
        expect(panel.className).toContain('visible')

        btn.click()
        await nextTick()
        expect(panel.className).not.toContain('visible')
    })
})
