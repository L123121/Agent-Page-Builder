/**
 * 内存对比基准测试：全量快照 vs 增量命令
 *
 * 模拟真实编辑场景（含 VText 文案、样式、动画等字段的组件）：
 *  - 快照方案：每次操作后 structuredClone 整个画布组件数组并保留在历史栈
 *  - 增量方案：每次操作只保存变更字段的命令（Move/Resize/StyleChange）
 *
 * 度量口径：保留数据结构序列化后的 UTF-8 字节数（JSON.stringify + Buffer.byteLength），
 * 该口径与对象字段数/字符串长度线性相关，是内存占用的稳定代理指标。
 *
 * 运行： npx vitest run src/commands/__tests__/memory-benchmark.test.ts
 */

import { describe, it, expect } from 'vitest'
import { MoveCommand } from '@/commands/MoveCommand'
import { ResizeCommand } from '@/commands/ResizeCommand'
import { StyleChangeCommand } from '@/commands/StyleChangeCommand'
import type { ComponentData } from '@/types'

/** 序列化保留数据的字节数（UTF-8） */
function bytesOf(value: unknown): number {
    return Buffer.byteLength(JSON.stringify(value), 'utf8')
}

/** 构造一个字段齐全的真实组件（VText，含文案/动画/事件/联动） */
function makeRichComponent(id: string, index: number): ComponentData {
    return {
        id,
        component: 'VText',
        label: `文本组件 ${index}`,
        icon: 'wenben',
        propValue: `这是一段用于模拟真实编辑场景的文案内容-${index}，包含足够长的文字来体现全量快照与增量记录的内存差异。`,
        style: {
            width: 240,
            height: 60,
            top: 20 + index * 10,
            left: 30 + index * 15,
            fontSize: 20,
            fontWeight: 400,
            color: '#333333',
            backgroundColor: 'rgba(255,255,255,0)',
            borderRadius: '0',
            borderWidth: 0,
            opacity: 1,
            rotate: 0,
            padding: 0,
            textAlign: 'left',
            lineHeight: '1.5',
            letterSpacing: 0,
            verticalAlign: 'middle',
        },
        parentId: null,
        slot: 'default',
        zIndex: 1,
        animations: [
            { type: 'fadeIn', label: '淡入', duration: 1, delay: 0, iterationNum: 1, infinite: false, applyTo: 'enter' },
        ],
        events: { click: 'alert:点击了组件' },
        groupStyle: {},
        isLock: false,
        collapseName: 'style',
        linkage: { duration: 0, data: [] },
    }
}

describe('撤销历史内存：全量快照 vs 增量命令', () => {
    it('报告实际内存降低百分比', () => {
        const COMPONENT_COUNT = 30
        const OPERATION_COUNT = 120

        // 构造初始画布
        const canvas: ComponentData[] = Array.from(
            { length: COMPONENT_COUNT },
            (_, i) => makeRichComponent(`c${i}`, i),
        )

        // ==================== 方案 A：全量快照 ====================
        // 每次操作后克隆整个画布数组并保留（模拟旧实现的撤销栈）
        const snapshotStack: ComponentData[][] = []
        const working = structuredClone(canvas)
        for (let i = 0; i < OPERATION_COUNT; i++) {
            const comp = working[i % COMPONENT_COUNT]
            const op = i % 3
            if (op === 0) {
                comp.style.top = 20 + i
                comp.style.left = 30 + i
            } else if (op === 1) {
                comp.style.width = 240 + i
                comp.style.height = 60 + i
            } else {
                comp.propValue = `修改后的文案内容-${i}，包含更长的文字来模拟用户编辑行为。`
            }
            snapshotStack.push(structuredClone(working))
        }

        // ==================== 方案 B：增量命令 ====================
        // 每次操作只保存变更字段（对应 Move/Resize/StyleChange 命令的 data）
        const commandStack: unknown[] = []
        for (let i = 0; i < OPERATION_COUNT; i++) {
            const id = `c${i % COMPONENT_COUNT}`
            const op = i % 3
            if (op === 0) {
                commandStack.push(
                    new MoveCommand(id, { top: 20 + i - 1, left: 30 + i - 1 }, { top: 20 + i, left: 30 + i }).serialize(),
                )
            } else if (op === 1) {
                commandStack.push(
                    new ResizeCommand(id, { width: 240 + i - 1, height: 60 + i - 1 }, { width: 240 + i, height: 60 + i }).serialize(),
                )
            } else {
                commandStack.push(
                    new StyleChangeCommand(id, 'propValue', `修改前的文案-${i}`, `修改后的文案内容-${i}，包含更长的文字来模拟用户编辑行为。`).serialize(),
                )
            }
        }

        // ==================== 度量 ====================
        const snapshotBytes = bytesOf(snapshotStack)
        const commandBytes = bytesOf(commandStack)
        const perOpSnapshot = snapshotBytes / OPERATION_COUNT
        const perOpCommand = commandBytes / OPERATION_COUNT
        const reduction = ((snapshotBytes - commandBytes) / snapshotBytes) * 100

        console.log('===== 撤销历史内存对比（120 次操作 × 30 组件画布） =====')
        console.log(`全量快照方案: ${(snapshotBytes / 1024).toFixed(1)} KB  (每操作 ${perOpSnapshot.toFixed(0)} B)`)
        console.log(`增量命令方案: ${(commandBytes / 1024).toFixed(1)} KB  (每操作 ${perOpCommand.toFixed(0)} B)`)
        console.log(`实际内存降低: ${reduction.toFixed(1)}%`)

        // 增量方案必须显著小于全量快照
        expect(commandBytes).toBeLessThan(snapshotBytes / 2)
    })
})
