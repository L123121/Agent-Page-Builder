/**
 * 页面管理 composable — 封装后端页面 CRUD 与分享
 *
 * 提供页面列表、创建、保存、打开、删除、分享等能力，
 * 自动与 Pinia store 的 componentData / canvasStyleData 同步。
 */

import { ref } from 'vue'
import { useStore } from '@/store'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { pagesApi, type PageSummary } from '@/utils/api'
import type { ComponentData, CanvasStyleData } from '@/types'

export function usePageManager() {
    const store = useStore()
    const { componentData, canvasStyleData } = storeToRefs(store)

    const pages = ref<PageSummary[]>([])
    const isLoading = ref(false)
    const isSaving = ref(false)

    /** 加载页面列表 */
    async function loadPages(): Promise<void> {
        isLoading.value = true
        try {
            const { pages: list } = await pagesApi.list()
            pages.value = list
        } catch (e) {
            ElMessage.error(`加载页面列表失败: ${e instanceof Error ? e.message : e}`)
        } finally {
            isLoading.value = false
        }
    }

    /** 创建新页面并设为当前编辑页 */
    async function createPage(title = '未命名页面'): Promise<void> {
        isSaving.value = true
        try {
            const { page } = await pagesApi.create({
                title,
                componentData: componentData.value,
                canvasStyle: canvasStyleData.value,
            })
            store.setCurrentPage(page._id, page.title)
            ElMessage.success('已创建新页面')
            await loadPages()
        } catch (e) {
            ElMessage.error(`创建失败: ${e instanceof Error ? e.message : e}`)
        } finally {
            isSaving.value = false
        }
    }

    /** 保存当前页面（有 ID 则更新，无 ID 则创建） */
    async function savePage(title?: string, options: { silent?: boolean } = {}): Promise<void> {
        isSaving.value = true
        store.isSaving = true
        try {
            const currentTitle = title ?? store.currentPageTitle ?? '未命名页面'
            if (store.currentPageId) {
                await pagesApi.update(store.currentPageId, {
                    title: currentTitle,
                    componentData: componentData.value,
                    canvasStyle: canvasStyleData.value,
                })
                if (title) store.currentPageTitle = title
            } else {
                const { page } = await pagesApi.create({
                    title: currentTitle,
                    componentData: componentData.value,
                    canvasStyle: canvasStyleData.value,
                })
                store.setCurrentPage(page._id, page.title)
            }
            store.markSynced()
            if (!options.silent) ElMessage.success('保存成功')
        } catch (e) {
            if (!options.silent) ElMessage.error(`保存失败: ${e instanceof Error ? e.message : e}`)
        } finally {
            isSaving.value = false
            store.isSaving = false
        }
    }

    /** 打开指定页面（加载其数据到画布） */
    async function openPage(pageId: string): Promise<void> {
        isLoading.value = true
        try {
            const { page } = await pagesApi.get(pageId)
            store.setComponentData(page.componentData as ComponentData[])
            store.setCanvasStyle(page.canvasStyle as CanvasStyleData)
            store.setCurrentPage(page._id, page.title)
            ElMessage.success('页面已打开')
        } catch (e) {
            ElMessage.error(`打开失败: ${e instanceof Error ? e.message : e}`)
        } finally {
            isLoading.value = false
        }
    }

    /** 删除指定页面 */
    async function deletePage(pageId: string): Promise<void> {
        try {
            await pagesApi.delete(pageId)
            if (store.currentPageId === pageId) {
                store.currentPageId = null
            }
            ElMessage.success('已删除')
            await loadPages()
        } catch (e) {
            ElMessage.error(`删除失败: ${e instanceof Error ? e.message : e}`)
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
