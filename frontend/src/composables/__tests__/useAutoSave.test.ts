import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { effectScope, nextTick, type EffectScope } from 'vue'
import { ElMessage } from 'element-plus'
import { useStore } from '@/store'
import { authState, getAuthOwner } from '@/utils/auth'
import { pagesApi, type PageInfo } from '@/utils/api'
import { CanvasStyleSchema } from '@/schemas'
import { readActiveDraft, readPageDraft, writePageDraft, type PageDraft } from '@/utils/pageDrafts'
import { useAutoSave } from '../useAutoSave'

vi.mock('@/utils/api', () => ({
    pagesApi: { create: vi.fn(), update: vi.fn(), get: vi.fn(), list: vi.fn() },
    getErrorMessage: (error: unknown) => error instanceof Error ? error.message : '请求失败',
}))
vi.mock('element-plus', () => ({
    ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
    ElMessageBox: { confirm: vi.fn() },
}))

const scopes: EffectScope[] = []
function start() {
    const scope = effectScope()
    scopes.push(scope)
    scope.run(useAutoSave)
    return scope
}

function storedDraft(overrides: Partial<PageDraft> = {}): PageDraft {
    return {
        schemaVersion: 1, owner: 'user:alice', pageId: 'A', draftId: 'draft-A', title: 'A',
        componentData: [], canvasStyle: CanvasStyleSchema.parse({}), dirty: false, savedAt: 1,
        ...overrides,
    }
}

beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    localStorage.clear()
    authState.username = 'alice'
    authState.accessToken = 'test-token'
    setActivePinia(createPinia())
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
    vi.mocked(pagesApi.list).mockResolvedValue({ pages: [] })
    vi.mocked(pagesApi.update).mockImplementation(async (id, data) => ({
        page: { ...data, _id: id, isPublic: false, createdAt: '', updatedAt: '' } as PageInfo,
    }))
})

afterEach(() => {
    scopes.splice(0).forEach(scope => scope.stop())
    vi.restoreAllMocks()
    vi.useRealTimers()
})

describe('自动保存与草稿恢复', () => {
    it('恢复当前账号的活动草稿，包括空画布和页面身份', () => {
        writePageDraft(storedDraft({ canvasStyle: CanvasStyleSchema.parse({ width: 640 }), dirty: true }))
        start()
        const store = useStore()
        expect(store.currentPageId).toBe('A')
        expect(store.currentDraftId).toBe('draft-A')
        expect(store.componentData).toEqual([])
        expect(store.canvasStyleData.width).toBe(640)
        expect(store.isDirty()).toBe(true)
    })

    it('已登录用户退出后可恢复未归属账号的旧版草稿', () => {
        localStorage.setItem('canvasData', '[]')
        localStorage.setItem('canvasStyle', JSON.stringify({ width: 666 }))
        start()
        expect(useStore().canvasStyleData.width).toBe(1200)
        authState.username = ''
        expect(useStore().canvasStyleData.width).toBe(666)
        expect(readActiveDraft('anonymous')?.canvasStyle.width).toBe(666)
        expect(readActiveDraft('user:alice')?.canvasStyle.width).toBe(1200)
    })

    it('恢复已同步草稿后不重复请求云端', async () => {
        writePageDraft(storedDraft())
        start()
        await vi.advanceTimersByTimeAsync(120000)
        expect(pagesApi.update).not.toHaveBeenCalled()
    })

    it('仅修改画布配置也标脏，先存本地再存云端，成功后不重复保存', async () => {
        const store = useStore()
        store.setCurrentPage('A')
        start()
        const version = store.dataVersion
        store.canvasStyleData.backgroundColor = '#123456'
        expect(store.dataVersion).toBeGreaterThan(version)
        await nextTick()
        await vi.advanceTimersByTimeAsync(300)
        expect(readPageDraft(getAuthOwner(), 'A', '')?.canvasStyle.backgroundColor).toBe('#123456')
        expect(pagesApi.update).not.toHaveBeenCalled()
        await vi.advanceTimersByTimeAsync(2700)
        expect(pagesApi.update).toHaveBeenCalledTimes(1)
        expect(store.isDirty()).toBe(false)
        await vi.advanceTimersByTimeAsync(120000)
        expect(pagesApi.update).toHaveBeenCalledTimes(1)
    })

    it('云端保存失败仍保留草稿，定时检查可以重试', async () => {
        const store = useStore()
        store.setCurrentPage('A')
        start()
        vi.mocked(pagesApi.update).mockRejectedValueOnce(new Error('backend unavailable'))
        store.canvasStyleData.width = 720
        await nextTick()
        await vi.advanceTimersByTimeAsync(3000)
        expect(store.isDirty()).toBe(true)
        expect(store.saveError).toBe('backend unavailable')
        expect(readActiveDraft(getAuthOwner())?.canvasStyle.width).toBe(720)
        await vi.advanceTimersByTimeAsync(57000)
        expect(pagesApi.update).toHaveBeenCalledTimes(2)
        expect(store.isDirty()).toBe(false)
    })

    it('离线只写本地，恢复网络后立即同步', async () => {
        const online = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
        const store = useStore()
        store.setCurrentPage('A')
        start()
        store.canvasStyleData.width = 900
        await nextTick()
        await vi.advanceTimersByTimeAsync(3000)
        expect(pagesApi.update).not.toHaveBeenCalled()
        expect(readActiveDraft(getAuthOwner())?.canvasStyle.width).toBe(900)
        online.mockReturnValue(true)
        window.dispatchEvent(new Event('online'))
        await vi.advanceTimersByTimeAsync(0)
        expect(pagesApi.update).toHaveBeenCalledTimes(1)
        expect(store.isDirty()).toBe(false)
    })

    it('退出前同步写入最后修改，不依赖退出时的网络请求', () => {
        const store = useStore()
        store.setCurrentPage('A')
        start()
        store.canvasStyleData.width = 888
        window.dispatchEvent(new Event('beforeunload', { cancelable: true }))
        expect(readActiveDraft(getAuthOwner())?.canvasStyle.width).toBe(888)
        expect(pagesApi.update).not.toHaveBeenCalled()
    })

    it('切换账号分别保留和恢复各自草稿，不继承前一账号的页面', async () => {
        const store = useStore()
        store.setCurrentPage('A')
        start()
        store.canvasStyleData.width = 333
        writePageDraft(storedDraft({ owner: 'user:bob', pageId: 'B', canvasStyle: CanvasStyleSchema.parse({ width: 444 }) }))
        authState.username = 'bob'
        expect(store.currentPageId).toBe('B')
        expect(store.canvasStyleData.width).toBe(444)
        expect(readPageDraft('user:alice', 'A', '')?.canvasStyle.width).toBe(333)
        expect(readPageDraft('user:bob', 'A', '')).toBeNull()
        authState.username = ''
        expect(store.currentPageId).toBeNull()
        expect(store.canvasStyleData.width).toBe(1200)
        authState.username = 'alice'
        expect(store.currentPageId).toBe('A')
        expect(store.canvasStyleData.width).toBe(333)
        await nextTick()
    })

    it('本地写入失败时提示备份，并在关闭页面前警告', async () => {
        const store = useStore()
        start()
        vi.spyOn(console, 'warn').mockImplementation(() => {})
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
        store.canvasStyleData.width = 999
        await nextTick()
        await vi.advanceTimersByTimeAsync(3000)
        expect(ElMessage.warning).toHaveBeenCalledTimes(1)
        const event = new Event('beforeunload', { cancelable: true })
        window.dispatchEvent(event)
        expect(event.defaultPrevented).toBe(true)
        expect(ElMessage.warning).toHaveBeenCalledTimes(1)
    })

    it('停止编辑器时保存草稿并取消后续自动请求', async () => {
        const store = useStore()
        store.setCurrentPage('A')
        const scope = start()
        store.canvasStyleData.width = 777
        scope.stop()
        expect(readActiveDraft(getAuthOwner())?.canvasStyle.width).toBe(777)
        await vi.advanceTimersByTimeAsync(120000)
        window.dispatchEvent(new Event('online'))
        expect(pagesApi.update).not.toHaveBeenCalled()
    })
})
