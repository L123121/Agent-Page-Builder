import type { Command, CommandManagerConfig, CommandEnvelope } from './types'
import { BatchCommand } from './BatchCommand'
import { deserializeStack } from './registry'

/**
 * 批量操作助手
 */
export class BatchOperation {
    private readonly batchCommand: BatchCommand
    private readonly manager: CommandManager

    constructor(manager: CommandManager, description: string) {
        this.manager = manager
        this.batchCommand = new BatchCommand(description)
    }

    add(command: Command): this {
        this.batchCommand.addCommand(command)
        return this
    }

    commit(): void {
        this.manager.execute(this.batchCommand)
    }
}

/**
 * 命令管理器 - 双栈撤销重做
 *
 * 内存管理：维护 undoStack 的 memoryWeight 总预算。
 * 全量快照命令（导入/清空画布）按组件数加权（memoryWeight = ceil(组件数/10)），
 * 普通增量命令 memoryWeight = 1。超出预算时从栈底淘汰最早命令，
 * 防止大画布长时间编辑导致 OOM。
 */
export class CommandManager {
    private undoStack: Command[] = []
    private redoStack: Command[] = []
    private readonly config: CommandManagerConfig
    /** 当前 undoStack 的内存权重总和 */
    private currentMemoryWeight = 0

    constructor(config: Partial<CommandManagerConfig> = {}) {
        this.config = {
            maxStackSize: config.maxStackSize ?? 50,
            mergeTimeWindow: config.mergeTimeWindow ?? 300,
            maxMemoryWeight: config.maxMemoryWeight ?? 50,
        }
    }

    /**
   * 执行命令并压入撤销栈
   */
    execute(command: Command): void {
        const lastCommand = this.undoStack[this.undoStack.length - 1]

        if (this.shouldMerge(lastCommand, command)) {
            const mergedCommand = lastCommand!.merge(command)
            // 合并时更新权重：减去旧命令权重，加上合并后权重
            this.currentMemoryWeight -= lastCommand!.memoryWeight
            this.undoStack[this.undoStack.length - 1] = mergedCommand
            mergedCommand.execute()
            this.currentMemoryWeight += mergedCommand.memoryWeight
            this.redoStack = []
            this.enforceMemoryBudget()
            return
        }

        command.execute()
        this.undoStack.push(command)
        this.currentMemoryWeight += command.memoryWeight
        this.redoStack = []

        if (this.undoStack.length > this.config.maxStackSize) {
            const removed = this.undoStack.shift()
            if (removed) this.currentMemoryWeight -= removed.memoryWeight
        }

        this.enforceMemoryBudget()
    }

    /**
     * 强制执行内存预算：从栈底淘汰最早命令，直到总权重 <= 预算上限。
     * 被淘汰的命令将不可撤销，但保证内存有界。
     */
    private enforceMemoryBudget(): void {
        const max = this.config.maxMemoryWeight
        let guard = 0
        while (this.currentMemoryWeight > max && this.undoStack.length > 1 && guard < 1000) {
            const removed = this.undoStack.shift()
            if (removed) this.currentMemoryWeight -= removed.memoryWeight
            guard++
        }
    }

    private shouldMerge(lastCommand: Command | undefined, command: Command): boolean {
        if (!lastCommand || !lastCommand.mergeable || !command.mergeable) {
            return false
        }

        const timeDiff = Math.abs(command.timestamp - lastCommand.timestamp)
        if (timeDiff > this.config.mergeTimeWindow) {
            return false
        }

        return lastCommand.canMergeWith(command, this.config.mergeTimeWindow)
    }

    undo(): boolean {
        const command = this.undoStack.pop()
        if (!command) return false

        command.undo()
        this.redoStack.push(command)
        this.currentMemoryWeight -= command.memoryWeight
        return true
    }

    redo(): boolean {
        const command = this.redoStack.pop()
        if (!command) return false

        command.redo()
        this.undoStack.push(command)
        this.currentMemoryWeight += command.memoryWeight
        return true
    }

    canUndo(): boolean {
        return this.undoStack.length > 0
    }

    canRedo(): boolean {
        return this.redoStack.length > 0
    }

    getUndoStackSize(): number {
        return this.undoStack.length
    }

    getRedoStackSize(): number {
        return this.redoStack.length
    }

    clear(): void {
        this.undoStack = []
        this.redoStack = []
        this.currentMemoryWeight = 0
    }

    beginBatch(description: string = '批量操作'): BatchOperation {
        return new BatchOperation(this, description)
    }

    // ==================== 跨会话序列化 ====================

    /**
     * 导出撤销栈为信封数组(可入 IndexedDB / localStorage)。
     * 仅导出 undoStack;redoStack 在跨会话后通常无意义(用户已离开)。
     */
    exportStack(): CommandEnvelope[] {
        return this.undoStack.map(cmd => cmd.serialize())
    }

    /**
     * 从信封数组恢复撤销栈(刷新后调用)。
     * 反序列化失败的命令跳过,保证向前兼容。
     */
    importStack(envelopes: CommandEnvelope[]): void {
        this.undoStack = deserializeStack(envelopes)
        this.redoStack = []
        // 重新计算内存权重
        this.currentMemoryWeight = this.undoStack.reduce((sum, cmd) => sum + cmd.memoryWeight, 0)
    }

    /**
     * 导出当前可撤销的命令描述列表(时间线 UI 用,不含敏感数据)。
     */
    getUndoDescriptions(): Array<{ id: string; description: string; timestamp: number }> {
        return this.undoStack.map(cmd => ({
            id: cmd.id,
            description: cmd.description,
            timestamp: cmd.timestamp,
        }))
    }
}
