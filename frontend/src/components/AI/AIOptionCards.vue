<template>
    <div class="ai-options">
        <div
            v-for="opt in options"
            :key="opt.id"
            class="ai-option-card"
            :class="{ disabled }"
            @click="$emit('select', opt)"
        >
            <div class="ai-option-header">
                <span class="ai-option-title">{{ opt.title }}</span>
                <el-tag
                    v-if="opt.tag"
                    size="small"
                    type="warning"
                    effect="plain"
                >
                    {{ opt.tag }}
                </el-tag>
            </div>
            <p class="ai-option-desc">
                {{ opt.description }}
            </p>
        </div>
    </div>
</template>

<script setup lang="ts">
import type { AIOption } from '@/api/ai'

defineProps<{
    options: AIOption[]
    disabled?: boolean
}>()

defineEmits<{ select: [option: AIOption] }>()
</script>

<style scoped lang="scss">
.ai-options {
    width: 100%;
    margin-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.ai-option-card {
    border: 1px solid #e4e7ed;
    border-radius: 10px;
    padding: 12px 14px;
    cursor: pointer;
    transition: all 0.2s;
    background: #fff;

    &:hover {
        border-color: #409eff;
        box-shadow: 0 2px 8px rgba(64, 158, 255, 0.15);
    }

    &.disabled {
        opacity: 0.5;
        pointer-events: none;
    }
}

.ai-option-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
}

.ai-option-title {
    font-size: 14px;
    font-weight: 600;
    color: #303133;
}

.ai-option-desc {
    font-size: 12px;
    color: #909399;
    margin: 0;
    line-height: 1.5;
}
</style>
