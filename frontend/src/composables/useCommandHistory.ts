/**
 * 命令历史持久化(跨会话)
 *
 * 监听 dataVersion 变化(每次命令执行/撤销都会递增),防抖后把撤销栈
 * 序列化(commandManager.exportStack())写入 IndexedDB。
 * 应用启动时从 IndexedDB 恢复栈(importCommandStack),刷新后仍可 Ctrl+Z。
 *
 * 注意:命令栈是"本地操作历史"。
 */

import { watch, onScopeDispose } from 'vue'
import { storeToRefs } from 'pinia'
import { useStore } from '@/store'
import type { CommandEnvelope } from '@/commands/types'
import { clearCommandHistory, exportCommandStack, importCommandStack } from '@/composables/useCommandActions'
import { getAuthOwner } from '@/utils/auth'
import { getDraftKey } from '@/utils/pageDrafts'

type PageStore = ReturnType<typeof useStore>
interface HistoryRecord {
    version: 1
    canvas: string
    envelopes: CommandEnvelope[]
}

const DB_NAME = 'lowcode-command-history'
const STORE_NAME = 'command-history'
const DEBOUNCE_MS = 800
const writers = new WeakMap<PageStore, () => Promise<void>>()

function historyKey(store: PageStore, owner = getAuthOwner()): string {
    return `history:${getDraftKey(owner, store.currentPageId, store.currentDraftId)}`
}

function canvasFingerprint(store: PageStore): string {
    return JSON.stringify([store.componentData, store.canvasStyleData])
}

export async function persistCommandHistory(store: PageStore): Promise<void> {
    await writers.get(store)?.()
}

// ==================== 最小 IndexedDB KV 封装 ====================

function openDB(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(DB_NAME, 1)
        req.onupgradeneeded = () => {
            const db = req.result
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME)
            }
        }
        req.onsuccess = () => resolve(req.result)
        req.onerror = () => reject(req.error)
    })
}

async function idbSet(key: string, value: unknown): Promise<void> {
    const db = await openDB()
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite')
        tx.objectStore(STORE_NAME).put(value, key)
        tx.oncomplete = () => { db.close(); resolve() }
        tx.onerror = () => { db.close(); reject(tx.error) }
        tx.onabort = () => { db.close(); reject(tx.error ?? new Error('历史写入已中断')) }
    })
}

async function idbGet<T>(key: string): Promise<T | null> {
    const db = await openDB()
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readonly')
        const req = tx.objectStore(STORE_NAME).get(key)
        tx.oncomplete = () => { db.close(); resolve((req.result as T) ?? null) }
        tx.onerror = () => { db.close(); reject(tx.error) }
        tx.onabort = () => { db.close(); reject(tx.error ?? new Error('历史读取已中断')) }
    })
}

// ==================== composable ====================

export function useCommandHistory(): void {
    const store = useStore()
    const { dataVersion } = storeToRefs(store)

    let saveTimer: ReturnType<typeof setTimeout> | null = null
    let lastSavedStamp = ''
    let owner = getAuthOwner()
    let writeQueue = Promise.resolve()
    let restoringVersion: number | null = null

    async function persist(): Promise<void> {
        if (restoringVersion === dataVersion.value) return
        const key = historyKey(store, owner)
        const stamp = `${key}:${dataVersion.value}`
        if (stamp === lastSavedStamp) return
        try {
            const record = JSON.parse(JSON.stringify({
                version: 1, canvas: canvasFingerprint(store), envelopes: exportCommandStack(),
            })) as HistoryRecord
            const write = writeQueue.then(() => idbSet(key, record))
            writeQueue = write.catch(() => {})
            await write
            if (key === historyKey(store, owner)) lastSavedStamp = stamp
        } catch (e) {
            console.error('[command-history] 持久化失败:', e)
        }
    }

    function restore(): void {
        const sessionId = store.pageSessionId
        restoringVersion = store.dataVersion
        clearCommandHistory()
        void restoreCommandHistory(writeQueue).finally(() => {
            if (sessionId === store.pageSessionId) restoringVersion = null
        })
    }

    writers.set(store, persist)
    watch(() => store.pageSessionId, () => {
        if (saveTimer) clearTimeout(saveTimer)
        owner = getAuthOwner()
        lastSavedStamp = ''
        restore()
    }, { flush: 'sync' })
    watch(() => store.currentPageId, () => schedulePersist())
    restore()

    function schedulePersist(): void {
        if (saveTimer) clearTimeout(saveTimer)
        saveTimer = setTimeout(() => {
            void persist()
        }, DEBOUNCE_MS)
    }

    // 防抖监听数据变更
    watch(dataVersion, () => {
        schedulePersist()
    })

    // 关闭前强制保存
    function handleBeforeUnload(): void {
        void persist()
    }
    window.addEventListener('beforeunload', handleBeforeUnload)

    onScopeDispose(() => {
        void persist()
        writers.delete(store)
        if (saveTimer) clearTimeout(saveTimer)
        window.removeEventListener('beforeunload', handleBeforeUnload)
    })
}

export async function restoreCommandHistory(pendingWrites: Promise<void> = Promise.resolve()): Promise<void> {
    const store = useStore()
    const owner = getAuthOwner()
    const sessionId = store.pageSessionId
    const version = store.dataVersion
    const key = historyKey(store, owner)
    try {
        await pendingWrites
        const record = await idbGet<HistoryRecord>(key)
        if (owner !== getAuthOwner() || sessionId !== store.pageSessionId || version !== store.dataVersion
            || key !== historyKey(store) || record?.version !== 1 || !Array.isArray(record.envelopes)) return
        if (record.canvas === canvasFingerprint(store)) importCommandStack(record.envelopes)
    } catch (e) {
        console.warn('[command-history] 恢复失败:', e)
    }
}
