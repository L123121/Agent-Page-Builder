import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { IDBFactory } from 'fake-indexeddb'
import { createPinia, setActivePinia } from 'pinia'
import { effectScope, type EffectScope } from 'vue'
import { useStore } from '@/store'
import { authState } from '@/utils/auth'
import { getDraftKey } from '@/utils/pageDrafts'
import { CommandType, type CommandEnvelope } from '@/commands/types'
import { clearCommandHistory, exportCommandStack, importCommandStack } from '../useCommandActions'
import { persistCommandHistory, restoreCommandHistory, useCommandHistory } from '../useCommandHistory'

vi.mock('../useCommandActions', () => ({
    clearCommandHistory: vi.fn(),
    exportCommandStack: vi.fn(),
    importCommandStack: vi.fn(),
}))

interface HistoryRecord {
    version: 1
    canvas: string
    envelopes: CommandEnvelope[]
}

const scopes: EffectScope[] = []
const keyA = `history:${getDraftKey('user:alice', 'A', '')}`

function record(): HistoryRecord {
    const store = useStore()
    return {
        version: 1,
        canvas: JSON.stringify([store.componentData, store.canvasStyleData]),
        envelopes: [{ id: 'move', type: CommandType.MOVE_COMPONENT, timestamp: 1, data: { left: 1 } }],
    }
}

async function stored(key: string, value?: HistoryRecord): Promise<HistoryRecord | undefined> {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open('lowcode-command-history', 1)
        request.onupgradeneeded = () => request.result.createObjectStore('command-history')
        request.onsuccess = () => resolve(request.result)
        request.onerror = () => reject(request.error)
    })
    return new Promise((resolve, reject) => {
        const tx = db.transaction('command-history', value ? 'readwrite' : 'readonly')
        const objectStore = tx.objectStore('command-history')
        const request = value ? objectStore.put(value, key) : objectStore.get(key)
        tx.oncomplete = () => { db.close(); resolve(value ?? request.result) }
        tx.onerror = () => { db.close(); reject(tx.error) }
    })
}

async function start(): Promise<void> {
    const scope = effectScope()
    scopes.push(scope)
    scope.run(useCommandHistory)
    await restoreCommandHistory()
}

beforeEach(() => {
    vi.resetAllMocks()
    vi.stubGlobal('indexedDB', new IDBFactory())
    localStorage.clear()
    authState.username = 'alice'
    setActivePinia(createPinia())
    const store = useStore()
    store.canvasStyleData.width = 600
    store.setCurrentPage('A')
    vi.mocked(exportCommandStack).mockReturnValue([])
})

afterEach(async () => {
    await persistCommandHistory(useStore())
    scopes.splice(0).forEach(scope => scope.stop())
    vi.unstubAllGlobals()
})

describe('按页面隔离的撤销历史', () => {
    it('只恢复与当前画布完全匹配的历史', async () => {
        const value = record()
        await stored(keyA, value)
        await restoreCommandHistory()
        expect(importCommandStack).toHaveBeenCalledWith(value.envelopes)
    })

    it('同一页面的云端内容已变化时不恢复旧历史', async () => {
        await stored(keyA, record())
        useStore().canvasStyleData.width = 700
        await restoreCommandHistory()
        expect(importCommandStack).not.toHaveBeenCalled()
    })

    it('不读取其他账号、其他页面或旧版全局历史', async () => {
        await stored(keyA, record())
        await stored('undoStack', record())
        authState.username = 'bob'
        await restoreCommandHistory()
        authState.username = 'alice'
        useStore().setCurrentPage('B')
        await restoreCommandHistory()
        expect(importCommandStack).not.toHaveBeenCalled()
    })

    it('恢复等待期间发生编辑时，不覆盖用户新历史', async () => {
        await stored(keyA, record())
        let release!: () => void
        const barrier = new Promise<void>(resolve => { release = resolve })
        const restoring = restoreCommandHistory(barrier)
        useStore().markDataDirty()
        release()
        await restoring
        expect(importCommandStack).not.toHaveBeenCalled()
    })

    it('离开后再返回相同页面，旧恢复请求也会失效', async () => {
        await stored(keyA, record())
        let release!: () => void
        const barrier = new Promise<void>(resolve => { release = resolve })
        const restoring = restoreCommandHistory(barrier)
        useStore().setCurrentPage('B')
        useStore().setCurrentPage('A')
        release()
        await restoring
        expect(importCommandStack).not.toHaveBeenCalled()
    })

    it('切页前捕获的历史只写入原页面，切页立即清空内存栈', async () => {
        await start()
        const store = useStore()
        store.markDataDirty()
        const original = record()
        vi.mocked(exportCommandStack).mockReturnValue(original.envelopes)
        const writing = persistCommandHistory(store)
        store.canvasStyleData.width = 800
        store.setCurrentPage('B')
        expect(clearCommandHistory).toHaveBeenCalledTimes(2)
        await writing
        expect(await stored(keyA)).toEqual(original)
        await restoreCommandHistory()
    })

    it('写入排队期间命令合并不会修改已捕获的历史记录', async () => {
        await start()
        const store = useStore()
        store.markDataDirty()
        const value = record()
        vi.mocked(exportCommandStack).mockReturnValue(value.envelopes)
        const writing = persistCommandHistory(store)
        value.envelopes[0].data.left = 200
        await writing
        expect((await stored(keyA))?.envelopes[0].data.left).toBe(1)
    })

    it('同一页面的连续历史写入保持版本顺序', async () => {
        await start()
        const store = useStore()
        store.markDataDirty()
        const first = persistCommandHistory(store)
        store.canvasStyleData.width = 900
        store.markDataDirty()
        const second = persistCommandHistory(store)
        await Promise.all([first, second])
        expect((await stored(keyA))?.canvas).toBe(JSON.stringify([store.componentData, store.canvasStyleData]))
    })
})
