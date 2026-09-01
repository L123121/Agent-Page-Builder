<template>
    <div class="ai-streaming">
        <div class="ai-streaming-header">
            <span class="ai-streaming-dot" />
            <span>Agent 执行中 · 第 {{ steps.length }} 步</span>
        </div>
        <div
            v-for="step in steps"
            :key="`${step.step}-${step.tool}`"
            class="ai-streaming-step"
            :class="step.status"
        >
            <span class="step-icon">
                {{ step.correction ? '🔁' :
                    step.status === 'done' ? '✅' :
                    step.status === 'error' ? '❌' :
                    step.status === 'running' ? '⏳' : '⏸' }}
            </span>
            <span class="step-tool">{{ step.correction ? correctionLabel(step) : (toolLabels[step.tool] || step.tool) }}</span>
            <span v-if="step.autoFixes?.length" class="step-fixes">
                修复 {{ step.autoFixes.length }} 项
            </span>
            <span v-if="step.validation && !step.validation.valid" class="step-warn">
                {{ step.validation.errorCount }} 错误
            </span>
        </div>
    </div>
</template>

<script setup lang="ts">
import type { StreamingStep } from '@/composables/useAIChat'

defineProps<{ steps: StreamingStep[] }>()

/** 工具名 → 中文标签 */
const toolLabels: Record<string, string> = {
    propose_options: '生成选项',
    ask_question: '提出问题',
    confirm_plan: '确认方案',
    generate_page: '生成页面',
    edit_page: '修改页面',
    finish: '完成',
}

/** 自省修正轮次：按反馈类型展示触发原因 */
const correctionLabels: Record<string, string> = {
    tool_not_allowed: '自省修正：调用了阶段外工具，已重试',
    unresolved_component_ref: '自省修正：组件引用无效，已重试',
    no_canvas_diff: '自省修正：动作未生效，已重试',
}

function correctionLabel(step: StreamingStep): string {
    return correctionLabels[step.correctionError || ''] || '自省修正：根据反馈重试'
}
</script>

<style scoped lang="scss">
.ai-streaming {
    margin-bottom: 12px;
    padding: 12px 14px;
    background: #f8f9fb;
    border: 1px solid #e4e7ed;
    border-radius: 10px;
}

.ai-streaming-header {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: #606266;
    margin-bottom: 8px;
}

.ai-streaming-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #409eff;
    animation: streaming-pulse 1.2s infinite;
}

@keyframes streaming-pulse {
    0%, 100% { opacity: 0.4; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.2); }
}

.ai-streaming-step {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 0;
    font-size: 12px;
    color: #303133;

    &.done { color: #67c23a; }
    &.error { color: #f56c6c; }
    &.running { color: #409eff; }
}

.step-icon {
    flex-shrink: 0;
    width: 16px;
    text-align: center;
}

.step-tool {
    font-weight: 500;
}

.step-fixes {
    font-size: 11px;
    color: #e6a23c;
    background: #fdf6ec;
    padding: 1px 6px;
    border-radius: 8px;
}

.step-warn {
    font-size: 11px;
    color: #f56c6c;
    background: #fef0f0;
    padding: 1px 6px;
    border-radius: 8px;
}
</style>
