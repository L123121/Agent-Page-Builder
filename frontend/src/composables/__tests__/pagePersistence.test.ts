import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { effectScope, type EffectScope } from 'vue'
import { useStore } from '@/store'
import { authState, getAuthOwner } from '@/utils/auth'
import { pagesApi, type PageInfo } from '@/utils/api'
import { readPageDraft } from '@/utils/pageDrafts'
import { persistCurrentDraft, saveCurrentPage } from '../pagePersistence'
import { usePageManager } from '../usePageManager'
import type { ComponentData } from '@/types'

vi.mock('@/utils/api', () => ({
    pagesApi: { create: vi.fn(), update: vi.fn(), get: vi.fn(), list: vi.fn() },
    getErrorMessage: (error: unknown) => error instanceof Error ? error.message : '请求失败',
}))
vi.mock('element-plus', () => ({
    ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
    ElMessageBox: { confirm: vi.fn() },
}))

function component(text = 'original'): ComponentData {
    return {
        id: 'text', component: 'VText', label: '文本', icon: '', propValue: text,
        style: { width: 100, height: 50 }, parentId: null, slot: 'default', zIndex: 1,
        animations: [], events: {}, groupStyle: {}, isLock: false, collapseName: 'style',
        linkage: { duration: 0, data: [] },
    }
}

function deferred<T>() {
    let resolve!: (value: T) => void
    let reject!: (reason: Error) => void
    const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
    return { promise, resolve, reject }
}

function response(id: string): { page: PageInfo } {
    return {
        page: {
            _id: id, title: id, componentData: [component(id)], canvasStyle: { ...useStore().canvasStyleData },
            isPublic: false, createdAt: '', updatedAt: '',
        },
    }
}

const scopes: EffectScope[] = []
function manager() {
    const scope = effectScope()
    scopes.push(scope)
    return scope.run(() => usePageManager())!
}

beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    authState.username = 'alice'
    authState.accessToken = 'test-token'
    setActivePinia(createPinia())
    const store = useStore()
    store.setComponentData([component()])
    store.setCurrentPage('A', 'A')
    store.markDataDirty()
    vi.mocked(pagesApi.list).mockResolvedValue({ pages: [] })
})

afterEach(() => {
    scopes.splice(0).forEach(scope => scope.stop())
})

describe('页面保存队列', () => {
    it('冻结请求数据，旧请求不能将后续编辑标为已同步', async () => {
        const store = useStore()
        const request = deferred<{ page: PageInfo }>()
        vi.mocked(pagesApi.update).mockReturnValueOnce(request.promise)
        const version = store.dataVersion
        const saving = saveCurrentPage(store)
        await Promise.resolve()
        store.componentData[0].propValue = 'new edit'
        store.markDataDirty()
        expect(vi.mocked(pagesApi.update).mock.calls[0][1].componentData?.[0].propValue).toBe('original')
        request.resolve(response('A'))
        expect((await saving).success).toBe(true)
        expect(store.lastSyncedVersion).toBe(version)
        expect(store.isDirty()).toBe(true)
        expect(readPageDraft(getAuthOwner(), 'A', '')?.componentData[0].propValue).toBe('new edit')
        expect(readPageDraft(getAuthOwner(), 'A', '')?.dirty).toBe(true)
    })

    it('不同 composable 实例共享队列，将多次保存合并为最新快照', async () => {
        const store = useStore()
        const first = deferred<{ page: PageInfo }>()
        const second = deferred<{ page: PageInfo }>()
        vi.mocked(pagesApi.update).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
        const one = manager()
        const two = manager()
        const saving = one.savePage(undefined, { silent: true })
        await Promise.resolve()
        store.componentData[0].propValue = 'intermediate'
        store.markDataDirty()
        const queued = two.savePage(undefined, { silent: true })
        store.componentData[0].propValue = 'latest'
        store.markDataDirty()
        const latest = one.savePage(undefined, { silent: true })
        expect(pagesApi.update).toHaveBeenCalledTimes(1)
        first.resolve(response('A'))
        await Promise.resolve()
        expect(pagesApi.update).toHaveBeenCalledTimes(2)
        expect(vi.mocked(pagesApi.update).mock.calls[1][1].componentData?.[0].propValue).toBe('latest')
        expect(one.isSaving.value).toBe(true)
        expect(two.isSaving.value).toBe(true)
        second.resolve(response('A'))
        await Promise.all([saving, queued, latest])
        expect(store.isDirty()).toBe(false)
        expect(store.isSaving).toBe(false)
    })

    it('相同版本的重复保存不会新增请求', async () => {
        const request = deferred<{ page: PageInfo }>()
        vi.mocked(pagesApi.update).mockReturnValueOnce(request.promise)
        const saving = saveCurrentPage(useStore())
        await Promise.resolve()
        const duplicate = saveCurrentPage(useStore())
        expect(duplicate).toBe(saving)
        request.resolve(response('A'))
        await saving
        expect(pagesApi.update).toHaveBeenCalledTimes(1)
    })

    it('新页面保存期间的后续修改使用更新接口，不重复创建页面', async () => {
        const store = useStore()
        store.setCurrentPage(null)
        const draftId = store.currentDraftId
        const first = deferred<{ page: PageInfo }>()
        vi.mocked(pagesApi.create).mockReturnValueOnce(first.promise)
        vi.mocked(pagesApi.update).mockResolvedValueOnce(response('created'))
        const saving = saveCurrentPage(store)
        await Promise.resolve()
        store.componentData[0].propValue = 'latest'
        store.markDataDirty()
        const queued = saveCurrentPage(store)
        first.resolve(response('created'))
        await Promise.all([saving, queued])
        expect(pagesApi.create).toHaveBeenCalledTimes(1)
        expect(pagesApi.update).toHaveBeenCalledWith('created', expect.anything(), { authOwner: getAuthOwner() })
        expect(store.currentPageId).toBe('created')
        expect(store.isDirty()).toBe(false)
        expect(readPageDraft(getAuthOwner(), null, draftId)).toBeNull()
        expect(readPageDraft(getAuthOwner(), 'created', '')?.dirty).toBe(false)
    })

    it('新页面迁移云端 ID 后切页，排队响应仍保留更晚的草稿', async () => {
        const store = useStore()
        store.setCurrentPage(null)
        const creation = deferred<{ page: PageInfo }>()
        const update = deferred<{ page: PageInfo }>()
        vi.mocked(pagesApi.create).mockReturnValueOnce(creation.promise)
        vi.mocked(pagesApi.update).mockReturnValueOnce(update.promise)
        const saving = saveCurrentPage(store)
        await Promise.resolve()
        store.componentData[0].propValue = 'queued'
        store.markDataDirty()
        const queued = saveCurrentPage(store)
        creation.resolve(response('created'))
        await Promise.resolve()
        store.componentData[0].propValue = 'last local edit'
        store.markDataDirty()
        persistCurrentDraft(store)
        store.setCurrentPage('B')
        update.resolve(response('created'))
        await Promise.all([saving, queued])
        const draft = readPageDraft(getAuthOwner(), 'created', '')
        expect(draft?.componentData[0].propValue).toBe('last local edit')
        expect(draft?.dirty).toBe(true)
    })

    it('切页后旧响应不改变新页面的同步状态或保存标志', async () => {
        const store = useStore()
        const first = deferred<{ page: PageInfo }>()
        const second = deferred<{ page: PageInfo }>()
        vi.mocked(pagesApi.update).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
        const savingA = saveCurrentPage(store)
        await Promise.resolve()
        store.setComponentData([component('B')])
        store.setCurrentPage('B', 'B')
        store.markDataDirty()
        const syncedB = store.lastSyncedVersion
        const savingB = saveCurrentPage(store)
        await Promise.resolve()
        first.resolve(response('A'))
        await savingA
        expect(store.currentPageId).toBe('B')
        expect(store.currentPageTitle).toBe('B')
        expect(store.lastSyncedVersion).toBe(syncedB)
        expect(store.isSaving).toBe(true)
        second.resolve(response('B'))
        await savingB
        expect(store.isSaving).toBe(false)
    })

    it('离开再返回同一页面时，旧会话响应仍不能确认新会话版本', async () => {
        const store = useStore()
        const request = deferred<{ page: PageInfo }>()
        vi.mocked(pagesApi.update).mockReturnValueOnce(request.promise)
        const saving = saveCurrentPage(store)
        await Promise.resolve()
        store.setCurrentPage('B')
        store.setCurrentPage('A')
        store.markDataDirty()
        const synced = store.lastSyncedVersion
        request.resolve(response('A'))
        await saving
        expect(store.lastSyncedVersion).toBe(synced)
        expect(store.isDirty()).toBe(true)
    })

    it('失败返回明确结果并保留最新草稿，允许重试', async () => {
        const store = useStore()
        const request = deferred<{ page: PageInfo }>()
        vi.mocked(pagesApi.update).mockReturnValueOnce(request.promise)
        const saving = saveCurrentPage(store)
        await Promise.resolve()
        store.componentData[0].propValue = 'unsaved'
        store.markDataDirty()
        request.reject(new Error('offline'))
        expect(await saving).toEqual({ success: false, error: 'offline' })
        expect(store.saveError).toBe('offline')
        expect(store.isSaving).toBe(false)
        expect(store.isDirty()).toBe(true)
        expect(readPageDraft(getAuthOwner(), 'A', '')?.componentData[0].propValue).toBe('unsaved')
        vi.mocked(pagesApi.update).mockResolvedValueOnce(response('A'))
        expect((await saveCurrentPage(store)).success).toBe(true)
        expect(store.saveError).toBeNull()
    })

    it('离开页面后的旧保存不能清除更新草稿的未同步标记', async () => {
        const store = useStore()
        const request = deferred<{ page: PageInfo }>()
        vi.mocked(pagesApi.update).mockReturnValueOnce(request.promise)
        const saving = saveCurrentPage(store)
        await Promise.resolve()
        store.componentData[0].propValue = 'new draft'
        store.markDataDirty()
        persistCurrentDraft(store)
        store.setComponentData([component('B')])
        store.setCurrentPage('B')
        request.resolve(response('A'))
        await saving
        const draft = readPageDraft(getAuthOwner(), 'A', '')
        expect(draft?.dirty).toBe(true)
        expect(draft?.componentData[0].propValue).toBe('new draft')
    })

    it('账号切换后不再发送旧账号排队的数据', async () => {
        const store = useStore()
        const request = deferred<{ page: PageInfo }>()
        vi.mocked(pagesApi.update).mockReturnValueOnce(request.promise)
        const saving = saveCurrentPage(store)
        await Promise.resolve()
        store.markDataDirty()
        const queued = saveCurrentPage(store)
        authState.username = 'bob'
        store.setCurrentPage('B')
        request.resolve(response('A'))
        expect((await saving).success).toBe(false)
        await queued
        expect(pagesApi.update).toHaveBeenCalledTimes(1)
        expect(store.currentPageId).toBe('B')
        expect(store.saveError).toBeNull()
        expect(readPageDraft('user:bob', 'A', '')).toBeNull()
    })
})

describe('页面加载', () => {
    it('连续打开不同页面时只应用最后一次请求', async () => {
        const one = deferred<{ page: PageInfo }>()
        const two = deferred<{ page: PageInfo }>()
        vi.mocked(pagesApi.get).mockReturnValueOnce(one.promise).mockReturnValueOnce(two.promise)
        const pages = manager()
        const first = pages.openPage('B')
        await Promise.resolve()
        await Promise.resolve()
        const second = pages.openPage('C')
        await Promise.resolve()
        await Promise.resolve()
        two.resolve(response('C'))
        expect(await second).toBe(true)
        one.resolve(response('B'))
        expect(await first).toBe(false)
        expect(useStore().currentPageId).toBe('C')
    })

    it('加载期间继续编辑，切页前仍保留最后的本地修改', async () => {
        const store = useStore()
        const request = deferred<{ page: PageInfo }>()
        vi.mocked(pagesApi.get).mockReturnValueOnce(request.promise)
        const opening = manager().openPage('B')
        await Promise.resolve()
        await Promise.resolve()
        store.componentData[0].propValue = 'last edit'
        store.markDataDirty()
        request.resolve(response('B'))
        expect(await opening).toBe(true)
        expect(readPageDraft(getAuthOwner(), 'A', '')?.componentData[0].propValue).toBe('last edit')
        expect(store.currentPageId).toBe('B')
    })
})
