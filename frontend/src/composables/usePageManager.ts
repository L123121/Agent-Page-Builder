/**
 * 页面管理 composable — 封装后端页面 CRUD 与分享
 *
 * 提供页面列表、创建、保存、打开、删除、分享等能力，
 * 自动与 Pinia store 的 componentData / canvasStyleData 同步。
 */

import { ref, computed, watch, onScopeDispose } from 'vue'
import { useStore } from '@/store'
import { ElMessage, ElMessageBox } from 'element-plus'
import { pagesApi, type PageSummary } from '@/utils/api'
import eventBus from '@/utils/eventBus'
import { getAuthOwner, isAuthenticated, requireLogin } from '@/utils/auth'
import { readPageDraft, removePageDraft, sameDraftContent, type PageDraft } from '@/utils/pageDrafts'
import generateID from '@/utils/generateID'
import { applyPageDraft, persistCurrentDraft, saveCurrentPage, waitForPageSave, type SaveResult } from './pagePersistence'
import { persistCommandHistory } from './useCommandHistory'

const openRequests = new WeakMap<ReturnType<typeof useStore>, number>()

export function usePageManager() {
    const store = useStore()
    const pages = ref<PageSummary[]>([])
    const isLoading = ref(false)
    const isSaving = computed(() => store.isSaving)
    let listRequest = 0

    /** 加载页面列表 */
    async function loadPages(): Promise<void> {
        const owner = getAuthOwner()
        const request = ++listRequest
        if (!isAuthenticated()) {
            pages.value = []
            return
        }
        isLoading.value = true
        try {
            const { pages: list } = await pagesApi.list()
            if (request === listRequest && owner === getAuthOwner()) pages.value = list
        } catch (e) {
            if (owner === getAuthOwner()) ElMessage.error(`加载页面列表失败: ${e instanceof Error ? e.message : e}`)
        } finally {
            if (request === listRequest) isLoading.value = false
        }
    }

    function handleLogin(): void {
        void loadPages()
    }
    eventBus.on('auth:login', handleLogin)
    watch(getAuthOwner, () => { pages.value = [] })
    onScopeDispose(() => {
        eventBus.off('auth:login', handleLogin)
    })

    function preserveBeforeSwitch(): boolean {
        void persistCommandHistory(store)
        if (persistCurrentDraft(store) || !store.isDirty()) return true
        ElMessage.error('本地草稿写入失败，请先保存或导出当前页面')
        return false
    }

    /** 创建新页面并设为当前编辑页 */
    async function createPage(title = '未命名页面'): Promise<boolean> {
        if (!isAuthenticated()) {
            requireLogin()
            return false
        }
        if (store.isSaving || !preserveBeforeSwitch()) return false
        store.setCurrentPage(null, title)
        const result = await savePage()
        if (result.success) await loadPages()
        return result.success
    }

    /** 保存当前页面（有 ID 则更新，无 ID 则创建） */
    async function savePage(title?: string, options: { silent?: boolean } = {}): Promise<SaveResult> {
        if (!isAuthenticated()) {
            const localSaved = persistCurrentDraft(store)
            const error = localSaved ? '请先登录，内容已保留在本地草稿' : '请先登录；本地草稿写入失败，请导出备份'
            store.saveError = error
            if (!options.silent) {
                requireLogin()
                ElMessage.warning(error)
            }
            return { success: false, error }
        }
        const sessionId = store.pageSessionId
        const owner = getAuthOwner()
        const result = await saveCurrentPage(store, title)
        if (!options.silent && sessionId === store.pageSessionId && owner === getAuthOwner()) {
            if (result.success) {
                ElMessage.success(store.isDirty() ? '已保存提交版本，新修改将继续自动保存' : '保存成功')
            } else {
                ElMessage.error(`保存失败: ${result.error}`)
            }
        }
        return result
    }

    /** 打开指定页面（加载其数据到画布） */
    async function openPage(pageId: string): Promise<boolean> {
        if (!preserveBeforeSwitch()) return false
        const owner = getAuthOwner()
        const sessionId = store.pageSessionId
        const version = store.dataVersion
        const request = (openRequests.get(store) ?? 0) + 1
        openRequests.set(store, request)
        const isCurrent = () => owner === getAuthOwner() && sessionId === store.pageSessionId
            && request === openRequests.get(store)
            && (store.currentPageId !== pageId || store.dataVersion === version)
        isLoading.value = true
        try {
            await waitForPageSave(store, owner, pageId)
            if (!isCurrent()) return false
            const { page } = await pagesApi.get(pageId, { authOwner: owner })
            if (!isCurrent()) return false
            const local = readPageDraft(owner, pageId, '')
            let draft: PageDraft = {
                schemaVersion: 1, owner, pageId, draftId: local?.draftId ?? generateID(),
                title: page.title, componentData: page.componentData, canvasStyle: page.canvasStyle,
                dirty: false, savedAt: Date.now(),
            }
            if (local?.dirty && !sameDraftContent(local, draft)) {
                try {
                    await ElMessageBox.confirm('该页面有未同步的本地草稿，是否恢复？', '恢复草稿', {
                        confirmButtonText: '恢复草稿', cancelButtonText: '使用云端版本',
                        distinguishCancelAndClose: true, type: 'warning',
                    })
                    draft = local
                } catch (action) {
                    if (action !== 'cancel') return false
                }
            }
            if (!isCurrent() || !preserveBeforeSwitch()) return false
            applyPageDraft(store, draft)
            persistCurrentDraft(store)
            ElMessage.success(draft.dirty ? '已恢复未同步的本地草稿' : '页面已打开')
            return true
        } catch (e) {
            if (!isCurrent()) return false
            const local = readPageDraft(owner, pageId, '')
            if (local && preserveBeforeSwitch()) {
                applyPageDraft(store, local)
                persistCurrentDraft(store)
                ElMessage.warning('云端页面暂不可用，已打开本地草稿')
                return true
            }
            ElMessage.error(`打开失败: ${e instanceof Error ? e.message : e}`)
            return false
        } finally {
            if (request === openRequests.get(store)) isLoading.value = false
        }
    }

    /** 删除指定页面 */
    async function deletePage(pageId: string): Promise<void> {
        const owner = getAuthOwner()
        const sessionId = store.pageSessionId
        try {
            await waitForPageSave(store, owner, pageId)
            if (owner !== getAuthOwner()) return
            await pagesApi.delete(pageId)
            if (owner !== getAuthOwner()) return
            const wasCurrent = store.currentPageId === pageId && sessionId === store.pageSessionId
            if (wasCurrent) {
                void persistCommandHistory(store)
                store.setCurrentPage(null, store.currentPageTitle)
                persistCurrentDraft(store)
            }
            removePageDraft(owner, pageId, '')
            ElMessage.success(wasCurrent ? '已删除，当前画布保留为本地草稿' : '已删除')
            await loadPages()
        } catch (e) {
            if (owner === getAuthOwner()) ElMessage.error(`删除失败: ${e instanceof Error ? e.message : e}`)
        }
    }

    /** 分享页面，返回分享链接 */
    async function sharePage(pageId: string): Promise<string | null> {
        try {
            const { shareUrl } = await pagesApi.share(pageId)
            ElMessage.success('分享链接已生成')
            await loadPages()
            return shareUrl
        } catch (e) {
            ElMessage.error(`分享失败: ${e instanceof Error ? e.message : e}`)
            return null
        }
    }

    /** 取消分享 */
    async function unsharePage(pageId: string): Promise<void> {
        try {
            await pagesApi.unshare(pageId)
            ElMessage.success('已取消分享')
            await loadPages()
        } catch (e) {
            ElMessage.error(`取消分享失败: ${e instanceof Error ? e.message : e}`)
        }
    }

    return {
        pages,
        isLoading,
        isSaving,
        loadPages,
        createPage,
        savePage,
        openPage,
        deletePage,
        sharePage,
        unsharePage,
    }
}
