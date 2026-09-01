<template>
    <div class="ai-plan" :class="{ disabled: resolved }">
        <p class="ai-plan-summary">
            {{ plan.summary }}
        </p>
        <ul class="ai-plan-details">
            <li v-for="(detail, i) in plan.details" :key="i">
                {{ detail }}
            </li>
        </ul>
        <div v-if="!resolved" class="ai-plan-actions">
            <el-button type="primary" size="small" @click="$emit('confirm')">
                确认生成
            </el-button>
            <el-button size="small" @click="$emit('reject')">
                我要修改
            </el-button>
        </div>
    </div>
</template>

<script setup lang="ts">
import type { AIPlan } from '@/api/ai'

defineProps<{
    plan: AIPlan
    resolved?: boolean
}>()

defineEmits<{
    confirm: []
    reject: []
}>()
</script>

<style scoped lang="scss">
.ai-plan {
    width: 100%;
    margin-top: 8px;
    border: 1px solid #e4e7ed;
    border-radius: 10px;
    padding: 14px;
    background: #fafafa;

    &.disabled {
        opacity: 0.6;
    }
}

.ai-plan-summary {
    font-size: 14px;
    font-weight: 600;
    color: #303133;
    margin: 0 0 10px;
}

.ai-plan-details {
    margin: 0 0 12px;
    padding-left: 18px;
    font-size: 12px;
    color: #606266;
    line-height: 1.8;
}

.ai-plan-actions {
    display: flex;
    gap: 8px;
}
</style>
