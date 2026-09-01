/**
 * AI 动作 → 画布命令：把 Agent 返回的 actions 翻译成可撤销的编辑器命令。
 *
 * 组件引用只接受精确 ID：后端已在 resolve_component_reference 中做过
 * ID/label 解析，下发的动作均携带有效 ID；前端不再做关键词模糊兜底
 * （模糊匹配会把「引用错误」悄悄变成「改错组件」，比失败更难排查）。
 */
import { useStore } from '@/store'
import {
    importDataWithCommand,
    addComponentWithCommand,
    deleteComponentWithCommand,
} from '@/composables/useCommandActions'
import { deepCopy } from '@/utils/utils'
import type { AIAction } from '@/api/ai'
import type { ComponentData } from '@/types'

export function useAIActions() {
    const store = useStore()

    function applyAIActions(actions: AIAction[]): void {
        // modify/move 批量合并为一次可撤销的整体替换（利用 ImportDataCommand）
        const modifyMoveActions = actions.filter(a => a.type === 'modify' || a.type === 'move')
        const otherActions = actions.filter(a => !['modify', 'move'].includes(a.type))

        if (modifyMoveActions.length > 0) {
            const allComponents = deepCopy(store.componentData)

            for (const action of modifyMoveActions) {
                const comp = allComponents.find(c => c.id === action.id)
                if (!comp) continue
                if (action.type === 'modify') {
                    if (action.style) Object.assign(comp.style, action.style)
                    if (action.propValue !== undefined) {
                        comp.propValue = action.propValue as ComponentData['propValue']
                    }
                } else if (action.type === 'move') {
                    if (action.top !== undefined) comp.style.top = action.top
                    if (action.left !== undefined) comp.style.left = action.left
                }
            }

            importDataWithCommand(allComponents)
        }

        for (const action of otherActions) {
            switch (action.type) {
                case 'generate':
                    if (action.components?.length) {
                        importDataWithCommand(action.components as ComponentData[], action.canvasStyle)
                    }
                    break
                case 'add':
                    if (action.component) {
                        addComponentWithCommand(action.component as ComponentData)
                    }
                    break
                case 'delete':
                    if (action.id && store.componentData.some(c => c.id === action.id)) {
                        deleteComponentWithCommand(action.id)
                    }
                    break
            }
        }
    }

    return { applyAIActions }
}
