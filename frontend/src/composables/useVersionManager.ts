/**
 * useVersionManager composable
 *
 * 版本管理：保存、恢复、删除页面版本快照。
 * - 已关联后端页面（currentPageId 存在）→ 版本快照存后端，跨设备可用
 * - 未关联后端页面 → localStorage 兜底（离线模式）
 */

import { useStore } from '@/store'
import { deepCopy } from '@/utils/utils'
import generateID from '@/utils/generateID'
import { validatePageVersions } from '@/utils/validation'
import { ElMessage } from 'element-plus'
import type { PageVersion } from '@/types'
import { importDataWithCommand } from '@/composables/useCommandActions'
import { pagesApi, getErrorMessage, type PageVersionSummary } from '@/utils/api'

const LOCAL_STORAGE_KEY = 'pageVersions'

function backendEnabled(): boolean {
    return !!useStore().currentPageId
}

async function reloadVersionsFromBackend(): Promise<void> {
    const store = useStore()
    if (!store.currentPageId) return
    const { versions } = await pagesApi.listVersions(store.currentPageId)
    store.versions = versions.map((v: PageVersionSummary) => ({
        id: v._id,
        name: v.name,
        description: v.description,
        createdAt: v.createdAt,
    }))
}

function saveVersionsToStorage(): void {
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(useStore().versions))
}

function loadVersionsFromLocalStorage(): void {
    const store = useStore()
    const data = localStorage.getItem(LOCAL_STORAGE_KEY)
    if (!data) return
    try {
        const parsed = JSON.parse(data)
        const result = validatePageVersions(parsed)
        if (result.success && result.data) {
            store.versions = result.data as unknown as PageVersion[]
        } else {
            console.warn('版本数据校验失败，已重置:', result.errors)
            store.versions = []
        }
    } catch {
        store.versions = []
    }
}

export async function saveVersion(name: string, description: string): Promise<void> {
    const store = useStore()
    if (backendEnabled()) {
        try {
            await pagesApi.createVersion(store.currentPageId!, {
                name,
                description,
                componentData: store.componentData,
                canvasStyle: store.canvasStyleData,
            })
            await reloadVersionsFromBackend()
            ElMessage.success('版本保存成功')
        } catch (error) {
            ElMessage.error(`版本保存失败: ${getErrorMessage(error)}`)
        }
        return
    }
    // localStorage 兜底
    const version: PageVersion = {
        id: generateID(),
        name,
        description,
        snapshot: deepCopy(store.componentData),
        createdAt: new Date().toISOString(),
    }
    store.versions.push(version)
    saveVersionsToStorage()
    ElMessage.success('版本保存成功')
}

export async function restoreVersion(versionId: string): Promise<void> {
    const store = useStore()
    const version = store.versions.find(v => v.id === versionId)
    if (!version) return

    if (backendEnabled()) {
        try {
            const { version: full } = await pagesApi.getVersion(store.currentPageId!, versionId)
            importDataWithCommand(full.componentData || [], full.canvasStyle)
            ElMessage.success('版本恢复成功')
        } catch (error) {
            ElMessage.error(`版本恢复失败: ${getErrorMessage(error)}`)
        }
        return
    }

    if (version.snapshot) {
        importDataWithCommand(deepCopy(version.snapshot))
        ElMessage.success('版本恢复成功')
    }
}

export async function deleteVersion(versionId: string): Promise<void> {
    const store = useStore()
    if (backendEnabled()) {
        try {
            await pagesApi.deleteVersion(store.currentPageId!, versionId)
            store.versions = store.versions.filter(v => v.id !== versionId)
            ElMessage.success('版本删除成功')
        } catch (error) {
            ElMessage.error(`版本删除失败: ${getErrorMessage(error)}`)
        }
        return
    }
    store.versions = store.versions.filter(v => v.id !== versionId)
    saveVersionsToStorage()
    ElMessage.success('版本删除成功')
}

export async function loadVersionsFromStorage(): Promise<void> {
    if (backendEnabled()) {
        try {
            await reloadVersionsFromBackend()
        } catch (error) {
            ElMessage.error(`版本加载失败: ${getErrorMessage(error)}`)
        }
        return
    }
    loadVersionsFromLocalStorage()
}
