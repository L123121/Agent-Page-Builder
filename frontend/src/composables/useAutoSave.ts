import { watch, onUnmounted } from 'vue'
import { useStore } from '@/store'
import { storeToRefs } from 'pinia'
import { usePageManager } from '@/composables/usePageManager'

/**
 * 自动保存 composable
 *
 * 使用脏标记（dirty flag）替代 deep watch：
 * - store 在每次数据变更时递增 dataVersion
 * - 这里 watch dataVersion（浅监听），避免 drag 期间每帧触发 deep watch
 * - 防抖 3 秒后写入，60 秒兜底保存
 *
 * 保存策略：
 * - 有 currentPageId（已关联后端页面）→ 保存到后端
 * - 否则 → 保存到 localStorage（离线兜底）
 */
export function useAutoSave(): void {
    const store = useStore()
    const { componentData, canvasStyleData, dataVersion, currentPageId } = storeToRefs(store)
    const { savePage } = usePageManager()

    let autosaveTimer: ReturnType<typeof setInterval> | null = null
    let saveTimeout: ReturnType<typeof setTimeout> | null = null
    let lastSavedVersion = 0

    // 浅监听 dataVersion —— 不会因 drag 期间 style 属性变化而触发
    watch(dataVersion, () => {
        scheduleAutosave()
    })

    // 画布配置变化频率低，保留 deep watch
    watch(canvasStyleData, () => {
        scheduleAutosave()
    }, { deep: true })

    function scheduleAutosave(): void {
        if (saveTimeout) clearTimeout(saveTimeout)
        saveTimeout = setTimeout(() => save(), 3000)
    }

    function save(): void {
        if (dataVersion.value === lastSavedVersion) return
        if (currentPageId.value) {
            // 有后端页面关联 → 静默同步到后端（不弹提示，避免打扰）
            savePage(undefined, { silent: true }).catch(() => {})
        } else {
            saveToLocalStorage()
        }
    }

    function saveToLocalStorage(): void {
        try {
            localStorage.setItem('canvasData', JSON.stringify(componentData.value))
            localStorage.setItem('canvasStyle', JSON.stringify(canvasStyleData.value))
            lastSavedVersion = dataVersion.value
        } catch (e) {
            console.error('自动保存失败:', e)
        }
    }

    function handleBeforeUnload(): void {
        save()
    }

    // 初始化
    window.addEventListener('beforeunload', handleBeforeUnload)
    autosaveTimer = setInterval(save, 60000)

    // 清理
    onUnmounted(() => {
        if (autosaveTimer) clearInterval(autosaveTimer)
        window.removeEventListener('beforeunload', handleBeforeUnload)
        if (saveTimeout) clearTimeout(saveTimeout)
    })
}
