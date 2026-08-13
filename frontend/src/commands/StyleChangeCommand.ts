import { BaseCommand, getContext } from './BaseCommand'
import { CommandType, type Command, type CommandEnvelope } from './types'
import { register } from './registry'
import { nanoid } from 'nanoid'

/**
 * 样式/文案变更数据（仅记录增量字段）
 *
 * key 支持嵌套路径：'propValue'、'style.color'、'propValue.flip.vertical'
 */
export interface StyleChangeData {
    componentId: string
    key: string
    oldValue: unknown
    newValue: unknown
}

/** 按路径读取嵌套值 */
function getNested(obj: Record<string, unknown>, path: string): unknown {
    return path.split('.').reduce<unknown>((acc, k) => {
        if (acc && typeof acc === 'object') {
            return (acc as Record<string, unknown>)[k]
        }
        return undefined
    }, obj)
}

/** 按路径写入嵌套值（原地修改） */
function setNested(obj: Record<string, unknown>, path: string, value: unknown): void {
    const keys = path.split('.')
    const lastKey = keys.pop()!
    const target = keys.reduce<Record<string, unknown>>((acc, k) => {
        const next = (acc as Record<string, unknown>)[k]
        if (next && typeof next === 'object') return next as Record<string, unknown>
        return (acc as Record<string, unknown>)[k] = {}
    }, obj)
    target[lastKey] = value
}

/** 深拷贝存储值，避免持有响应式/共享引用 */
function cloneValue(value: unknown): unknown {
    if (value && typeof value === 'object') {
        return structuredClone(value)
    }
    return value
}

/**
 * 文案/样式变更命令 —— 仅记录增量字段（componentId + key + 新旧值）。
 *
 * 相比全量快照（structuredClone 整个组件/画布），每条命令只保存被修改的
 * 单个字段，是撤销栈内存优化的核心增量命令。
 */
export class StyleChangeCommand extends BaseCommand {
    type = CommandType.STYLE_CHANGE
    description = '修改属性'
    mergeable = true

    private styleChangeData: StyleChangeData

    constructor(componentId: string, key: string, oldValue: unknown, newValue: unknown) {
        super()
        this.id = nanoid()
        this.styleChangeData = {
            componentId,
            key,
            oldValue: cloneValue(oldValue),
            newValue: cloneValue(newValue),
        }
        this.data = this.styleChangeData as unknown as Record<string, unknown>
    }

    private apply(value: unknown): void {
        const ctx = getContext()
        const comp = ctx.get(this.styleChangeData.componentId)
        if (!comp) return
        const path = this.styleChangeData.key
        const keys = path.split('.')
        const topKey = keys[0]

        if (topKey === 'style') {
            const style = { ...(comp.style as unknown as Record<string, unknown>) }
            setNested(style, path, value)
            ctx.setStyle(this.styleChangeData.componentId, style)
        } else if (keys.length === 1) {
            // 单层非样式字段（如 VText 的 propValue 字符串）：直接整体替换
            ctx.setProp(this.styleChangeData.componentId, { [topKey]: value } as Record<string, unknown>)
        } else {
            // 嵌套非样式字段（如 propValue.flip.vertical）：浅拷贝顶层对象后写路径
            const current = (comp as unknown as Record<string, unknown>)[topKey]
            const prop = current && typeof current === 'object'
                ? { ...(current as Record<string, unknown>) }
                : {}
            setNested(prop, path, value)
            ctx.setProp(this.styleChangeData.componentId, { [topKey]: prop } as Record<string, unknown>)
        }
    }

    execute(): void {
        this.apply(this.styleChangeData.newValue)
    }

    undo(): void {
        this.apply(this.styleChangeData.oldValue)
    }

    canMergeWith(other: Command, _mergeTimeWindow: number): boolean {
        if (other.type !== CommandType.STYLE_CHANGE) return false
        if (!(other instanceof StyleChangeCommand)) return false

        return (
            this.styleChangeData.componentId === other.styleChangeData.componentId
            && this.styleChangeData.key === other.styleChangeData.key
        )
    }

    merge(other: Command): StyleChangeCommand {
        if (!(other instanceof StyleChangeCommand)) return this

        return new StyleChangeCommand(
            this.styleChangeData.componentId,
            this.styleChangeData.key,
            this.styleChangeData.oldValue,
            other.styleChangeData.newValue,
        )
    }
}

register(CommandType.STYLE_CHANGE, (env: CommandEnvelope) => {
    const d = env.data as unknown as StyleChangeData
    const cmd = new StyleChangeCommand(d.componentId, d.key, d.oldValue, d.newValue)
    cmd.id = env.id
    return cmd
})
