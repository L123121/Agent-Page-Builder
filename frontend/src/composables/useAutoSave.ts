import { watch, onScopeDispose } from 'vue'
import { useStore } from '@/store'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { usePageManager } from '@/composables/usePageManager'
import { applyPageDraft, persistCurrentDraft } from './pagePersistence'
import { persistCommandHistory } from './useCommandHistory'
import { getAuthOwner, isAuthenticated } from '@/utils/auth'
import { readActiveDraft, migrateLegacyDraft } from '@/utils/pageDrafts'
import { CanvasStyleSchema } from '@/schemas'
import generateID from '@/utils/generateID'

const initializedStores = new WeakSet<ReturnType<typeof useStore>>()
const LOCAL_SAVE_DELAY = 300
const CLOUD_SAVE_DELAY = 3000
const LOCAL_SAVE_ERROR = '本地草稿写入失败，请及时保存到云端或导出备份'

export function useAutoSave(): void {
    const store = useStore()
    const { canvasStyleData, dataVersion, currentPageId, currentDraftId, pageSessionId } = storeToRefs(store)
    const { savePage } = usePageManager()

    if (!initializedStores.has(store)) {
        initializedStores.add(store)
        const owner = getAuthOwner()
        const draft = readActiveDraft(owner) ?? (owner === 'anonymous' ? migrateLegacyDraft(store.currentDraftId) : null)
        if (draft && store.pageSessionId === 0 && store.dataVersion === 0) applyPageDraft(store, draft)
    }

    let cloudTimer: ReturnType<typeof setTimeout> | null = null
    let localTimer: ReturnType<typeof setTimeout> | null = null
    let lastDraftStamp = ''
    let storageWarningShown = false

    function saveLocal(force = false, owner = getAuthOwner()): boolean {
        const stamp = JSON.stringify([
            owner, store.pageSessionId, store.currentPageId, store.currentDraftId,
            store.dataVersion, store.lastSyncedVersion, store.currentPageTitle,
        ])
        if (!force && stamp === lastDraftStamp) return true
        const saved = persistCurrentDraft(store, owner)
        if (saved) {
            lastDraftStamp = stamp
            storageWarningShown = false
            if (store.saveError === LOCAL_SAVE_ERROR) store.saveError = null
        } else {
            store.saveError = LOCAL_SAVE_ERROR
            if (!storageWarningShown) {
                storageWarningShown = true
                ElMessage.warning(LOCAL_SAVE_ERROR)
            }
        }
        return saved
    }

    function clearTimers(): void {
        if (localTimer) clearTimeout(localTimer)
        if (cloudTimer) clearTimeout(cloudTimer)
        localTimer = null
        cloudTimer = null
    }

    function save(): void {
        saveLocal()
        if (store.currentPageId && store.isDirty() && isAuthenticated() && navigator.onLine) {
            void savePage(undefined, { silent: true })
        }
    }

    function scheduleAutosave(): void {
        clearTimers()
        localTimer = setTimeout(() => saveLocal(), LOCAL_SAVE_DELAY)
        cloudTimer = setTimeout(save, CLOUD_SAVE_DELAY)
    }

    watch(dataVersion, scheduleAutosave)
    watch(canvasStyleData, () => store.markDataDirty(), { deep: true, flush: 'sync' })
    watch([pageSessionId, currentPageId, currentDraftId], () => {
        lastDraftStamp = ''
        saveLocal()
        scheduleAutosave()
    })
    watch(getAuthOwner, (owner, previousOwner) => {
        clearTimers()
        void persistCommandHistory(store)
        saveLocal(true, previousOwner)
        const draft = readActiveDraft(owner) ?? (owner === 'anonymous' ? migrateLegacyDraft(generateID()) : null)
        applyPageDraft(store, draft ?? {
            schemaVersion: 1, owner, pageId: null, draftId: generateID(), title: '未命名页面',
            componentData: [], canvasStyle: CanvasStyleSchema.parse({}), dirty: true, savedAt: Date.now(),
        })
        lastDraftStamp = ''
        saveLocal()
        scheduleAutosave()
    }, { flush: 'sync' })

    function handlePageHide(): void {
        saveLocal(true)
    }

    function handleBeforeUnload(event: BeforeUnloadEvent): void {
        if (!saveLocal(true) && store.isDirty()) {
            event.preventDefault()
            event.returnValue = ''
        }
    }

    function handleVisibilityChange(): void {
        if (document.visibilityState === 'hidden') saveLocal(true)
    }

    function handleOffline(): void {
        const saved = saveLocal(true)
        if (store.currentPageId && store.isDirty()) {
            store.saveError = saved ? '网络已断开，修改已保留在本地草稿' : '网络已断开，本地草稿写入失败，请导出备份'
        }
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    window.addEventListener('pagehide', handlePageHide)
    window.addEventListener('online', save)
    window.addEventListener('offline', handleOffline)
    document.addEventListener('visibilitychange', handleVisibilityChange)
    const interval = setInterval(save, 60000)
    saveLocal()
    scheduleAutosave()

    onScopeDispose(() => {
        saveLocal(true)
        clearTimers()
        clearInterval(interval)
        window.removeEventListener('beforeunload', handleBeforeUnload)
        window.removeEventListener('pagehide', handlePageHide)
        window.removeEventListener('online', save)
        window.removeEventListener('offline', handleOffline)
        document.removeEventListener('visibilitychange', handleVisibilityChange)
    })
}
