import type { useStore } from '@/store'
import { pagesApi, getErrorMessage } from '@/utils/api'
import { getAuthOwner } from '@/utils/auth'
import {
    acknowledgeDraft, getDraftKey, removePageDraft, writePageDraft,
    type PageDraft,
} from '@/utils/pageDrafts'

type PageStore = ReturnType<typeof useStore>

interface SaveSnapshot extends PageDraft {
    sessionId: number
    version: number
}

export type SaveResult =
    | { success: true; pageId: string; version: number }
    | { success: false; error: string }

interface SaveJob {
    pageId: string | null
    current: SaveSnapshot | null
    pending: SaveSnapshot | null
    promise: Promise<SaveResult>
}

const queues = new WeakMap<PageStore, Map<string, SaveJob>>()

function getQueue(store: PageStore): Map<string, SaveJob> {
    let queue = queues.get(store)
    if (!queue) {
        queue = new Map()
        queues.set(store, queue)
    }
    return queue
}

export function capturePageDraft(store: PageStore, owner = getAuthOwner()): PageDraft {
    return {
        schemaVersion: 1,
        owner,
        pageId: store.currentPageId,
        draftId: store.currentDraftId,
        title: store.currentPageTitle,
        componentData: store.componentData,
        canvasStyle: store.canvasStyleData,
        dirty: !store.currentPageId || store.isDirty(),
        savedAt: Date.now(),
    }
}

export function persistCurrentDraft(store: PageStore, owner = getAuthOwner()): boolean {
    return writePageDraft(capturePageDraft(store, owner))
}

export function applyPageDraft(store: PageStore, draft: PageDraft): void {
    store.setComponentData(draft.componentData)
    store.setCanvasStyle(draft.canvasStyle)
    store.setCurrentPage(draft.pageId, draft.title, {
        draftId: draft.draftId,
        syncedVersion: draft.dirty ? -1 : store.dataVersion,
    })
}

function isCurrentSession(store: PageStore, snapshot: SaveSnapshot): boolean {
    return snapshot.owner === getAuthOwner()
        && snapshot.sessionId === store.pageSessionId
        && snapshot.draftId === store.currentDraftId
}

function updateSavingState(store: PageStore): void {
    store.isSaving = [...getQueue(store).values()].some(job =>
        (job.current && isCurrentSession(store, job.current))
        || (job.pending && isCurrentSession(store, job.pending)),
    )
}

async function drainQueue(store: PageStore, job: SaveJob): Promise<SaveResult> {
    const queue = getQueue(store)
    let result: SaveResult = { success: false, error: '没有待保存的内容' }
    try {
        while (job.pending) {
            const snapshot = job.pending
            job.pending = null
            job.current = snapshot
            updateSavingState(store)
            if (snapshot.owner !== getAuthOwner()) throw new Error('登录账号已变化，请重新保存')
            const payload = {
                title: snapshot.title,
                componentData: snapshot.componentData,
                canvasStyle: snapshot.canvasStyle,
            }
            const config = { authOwner: snapshot.owner }
            const response = job.pageId
                ? await pagesApi.update(job.pageId, payload, config)
                : await pagesApi.create(payload, config)
            job.pageId = response.page._id
            queue.set(getDraftKey(snapshot.owner, job.pageId, snapshot.draftId), job)
            if (isCurrentSession(store, snapshot)) {
                store.currentPageId = job.pageId
                store.markSynced(snapshot.version)
                store.saveError = null
                if (persistCurrentDraft(store) && !snapshot.pageId) {
                    removePageDraft(snapshot.owner, null, snapshot.draftId)
                }
            } else {
                acknowledgeDraft(snapshot, job.pageId)
            }
            result = { success: true, pageId: job.pageId, version: snapshot.version }
        }
        return result
    } catch (error) {
        const message = getErrorMessage(error, '保存失败')
        const snapshot = job.pending ?? job.current
        if (snapshot && isCurrentSession(store, snapshot)) {
            store.saveError = message
            persistCurrentDraft(store)
        }
        return { success: false, error: message }
    } finally {
        for (const [key, value] of queue) {
            if (value === job) queue.delete(key)
        }
        updateSavingState(store)
    }
}

export function saveCurrentPage(store: PageStore, title?: string): Promise<SaveResult> {
    if (title !== undefined && title !== store.currentPageTitle) {
        store.currentPageTitle = title
        store.markDataDirty()
    }
    persistCurrentDraft(store)
    let snapshot: SaveSnapshot
    try {
        snapshot = JSON.parse(JSON.stringify({
            ...capturePageDraft(store),
            sessionId: store.pageSessionId,
            version: store.dataVersion,
        })) as SaveSnapshot
    } catch (error) {
        const message = getErrorMessage(error, '页面数据无法序列化')
        store.saveError = message
        return Promise.resolve({ success: false, error: message })
    }
    const queue = getQueue(store)
    const key = getDraftKey(snapshot.owner, snapshot.pageId, snapshot.draftId)
    const existing = queue.get(key)
    if (existing) {
        const latest = existing.pending ?? existing.current
        if (!latest || snapshot.version !== latest.version || snapshot.title !== latest.title
            || snapshot.sessionId !== latest.sessionId) {
            existing.pending = snapshot
        }
        updateSavingState(store)
        return existing.promise
    }
    const job: SaveJob = {
        pageId: snapshot.pageId,
        current: null,
        pending: snapshot,
        promise: Promise.resolve().then(() => drainQueue(store, job)),
    }
    queue.set(key, job)
    store.saveError = null
    updateSavingState(store)
    return job.promise
}

export async function waitForPageSave(store: PageStore, owner: string, pageId: string): Promise<void> {
    await getQueue(store).get(getDraftKey(owner, pageId, ''))?.promise
}
