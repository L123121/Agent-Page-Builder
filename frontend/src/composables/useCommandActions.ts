/**
 * useCommandActions composable
 *
 * 命令操作统一入口。将 CommandManager 及所有命令相关操作从 Pinia store 中剥离，
 * 使 store 专注于纯状态管理。
 *
 * 使用:
 *   const { undo, redo, moveComponent, ... } = useCommandActions()
 *
 * CommandManager 为模块级单例，跨组件共享同一 undo/redo 栈。
 * 所有命令通过此 composable 执行，自动标记 store 为脏。
 *
 * 模块级便捷函数（同文件底部）供非 setup 环境使用（如 shortcutKey.ts）。
 * composable 委托给模块级函数，保证逻辑单一真相源。
 */

import { useStore } from '@/store'
import type { Command } from '@/commands/types'
import { CommandManager } from '@/commands/CommandManager'
import { setCommandContext } from '@/commands/BaseCommand'
import { createLocalCommandContext } from '@/commands/localContext'
import type { ComponentData, ComponentStyle, CanvasStyleData } from '@/types'
import eventBus from '@/utils/eventBus'
import {
    MoveCommand,
    ResizeCommand,
    RotateCommand,
    StyleChangeCommand,
    AddComponentCommand,
    DeleteComponentCommand,
    LayerCommand,
    ComposeCommand,
    DecomposeCommand,
    ClearCanvasCommand,
    ImportDataCommand,
    CutCommand,
    PasteCommand,
} from '@/commands'
import type { CommandEnvelope } from '@/commands/types'

// ==================== 命令管理器单例 ====================

const commandManager = new CommandManager({ mergeTimeWindow: 300 })

/**
 * 注入命令上下文(本地实现,不涉及 Yjs)。
 * 命令经 ctx 直接操作 Pinia store 的 componentData 数组。
 */
export function initCommandContext(): void {
    setCommandContext(createLocalCommandContext())
}

/**
 * useCommandActions composable — 委托给模块级函数，逻辑单一真相源。
 */
export function useCommandActions() {
    return {
        executeCommand,
        undo,
        redo,
        canUndo,
        canRedo,
        clearCommandHistory,
        exportCommandStack,
        importCommandStack,
        getCommandTimeline,
        undoUntil,
        refreshCurComponent,
        moveComponent,
        resizeComponent,
        rotateComponent,
        changeStyleWithCommand,
        addComponentWithCommand,
        deleteComponentWithCommand,
        layerOperation,
        composeWithCommand,
        decomposeWithCommand,
        clearCanvasWithCommand,
        cutWithCommand,
        importDataWithCommand,
        pasteWithCommand,
    }
}

// ==================== 内部辅助 ====================

function executeCommand(command: Command): void {
    const store = useStore()
    commandManager.execute(command)
    store.markDataDirty()
}

function refreshCurComponent(): void {
    const store = useStore()
    if (store.curComponent) {
        const idx = store.componentData.findIndex(c => c.id === store.curComponent!.id)
        if (idx !== -1) {
            store.setCurComponent({ component: store.componentData[idx], index: idx })
        } else {
            store.setCurComponent({ component: null, index: null })
        }
    }
}

// ==================== 模块级便捷函数（非 setup 环境使用） ====================
// 用于 shortcutKey.ts 等无法调用 useCommandActions() 的环境。
// 通过 store.markDataDirty() 触发自动保存。

export function undo(): void {
    const store = useStore()
    commandManager.undo()
    refreshCurComponent()
    store.markDataDirty()
}

export function redo(): void {
    const store = useStore()
    commandManager.redo()
    refreshCurComponent()
    store.markDataDirty()
}

export function canUndo(): boolean {
    return commandManager.canUndo()
}

export function canRedo(): boolean {
    return commandManager.canRedo()
}

export function clearCommandHistory(): void {
    commandManager.clear()
}

export function exportCommandStack(): CommandEnvelope[] {
    return commandManager.exportStack()
}

export function importCommandStack(envelopes: CommandEnvelope[]): void {
    commandManager.importStack(envelopes)
}

export function getCommandTimeline(): Array<{ id: string; description: string; timestamp: number }> {
    return commandManager.getUndoDescriptions()
}

export function undoUntil(targetId: string): void {
    while (commandManager.canUndo()) {
        const timeline = commandManager.getUndoDescriptions()
        const top = timeline[timeline.length - 1]
        if (!top || top.id === targetId) break
        undo()
    }
}

export function moveComponent(componentId: string, oldStyle: Partial<ComponentStyle>, newStyle: Partial<ComponentStyle>): void {
    const store = useStore()
    commandManager.execute(new MoveCommand(componentId, oldStyle, newStyle))
    store.markDataDirty()
}

export function resizeComponent(componentId: string, oldStyle: Partial<ComponentStyle>, newStyle: Partial<ComponentStyle>): void {
    const store = useStore()
    commandManager.execute(new ResizeCommand(componentId, oldStyle, newStyle))
    store.markDataDirty()
}

export function rotateComponent(componentId: string, oldRotate: number, newRotate: number): void {
    const store = useStore()
    commandManager.execute(new RotateCommand(componentId, oldRotate, newRotate))
    store.markDataDirty()
}

/**
 * 文案/样式字段变更（增量命令，仅记录 key + 新旧值）。
 * key 支持嵌套路径：'propValue'、'style.color'、'propValue.flip.vertical'
 */
export function changeStyleWithCommand(componentId: string, key: string, oldValue: unknown, newValue: unknown): void {
    const store = useStore()
    if (oldValue === newValue) return
    commandManager.execute(new StyleChangeCommand(componentId, key, oldValue, newValue))
    store.markDataDirty()
}

export function addComponentWithCommand(component: ComponentData, index?: number): void {
    const store = useStore()
    commandManager.execute(new AddComponentCommand(component, index))
    store.markDataDirty()
}

export function deleteComponentWithCommand(id?: string, index?: number): void {
    const store = useStore()
    const componentId = id ?? store.curComponent?.id
    if (!componentId) return
    commandManager.execute(new DeleteComponentCommand(componentId, index))
    store.markDataDirty()
}

export function layerOperation(componentId: string, action: 'up' | 'down' | 'top' | 'bottom'): void {
    const store = useStore()
    commandManager.execute(new LayerCommand(componentId, action))
    store.markDataDirty()
}

export function composeWithCommand(): void {
    const store = useStore()
    const componentIds = store.areaData.components.map(c => c.id)
    if (componentIds.length > 0) {
        commandManager.execute(new ComposeCommand(componentIds))
        store.markDataDirty()
        eventBus.emit('hideArea')
    }
}

export function decomposeWithCommand(): void {
    const store = useStore()
    if (store.curComponent && store.curComponent.component === 'Group') {
        commandManager.execute(new DecomposeCommand(store.curComponent.id))
        store.markDataDirty()
    }
}

export function clearCanvasWithCommand(): void {
    const store = useStore()
    commandManager.execute(new ClearCanvasCommand())
    store.markDataDirty()
}

export function cutWithCommand(id?: string, index?: number): void {
    const store = useStore()
    const componentId = id ?? store.curComponent?.id
    if (!componentId) return
    commandManager.execute(new CutCommand(componentId, index))
    store.markDataDirty()
}

export function importDataWithCommand(componentData: ComponentData[], canvasStyle?: CanvasStyleData): void {
    const store = useStore()
    commandManager.execute(new ImportDataCommand(componentData, canvasStyle))
    store.markDataDirty()
}

export function pasteWithCommand(isMouse?: boolean): void {
    const store = useStore()
    if (!store.copyData) return
    commandManager.execute(new PasteCommand(store.copyData.data, isMouse, store.menuTop, store.menuLeft))
    store.markDataDirty()
}

export { refreshCurComponent }

export { CommandManager } from '@/commands/CommandManager'
export { BatchOperation } from '@/commands/CommandManager'
