<template>
    <div class="ai-empty">
        <p class="ai-empty-title">
            描述你想要的页面，AI 帮你生成
        </p>
        <p class="ai-empty-sub">
            一步步引导你完成设计，生成后可以自由修改
        </p>
        <div class="ai-examples">
            <el-tag
                v-for="ex in examples"
                :key="ex"
                class="ai-example-tag"
                effect="plain"
                @click="$emit('select', ex)"
            >
                {{ ex }}
            </el-tag>
        </div>
    </div>
</template>

<script setup lang="ts">
defineProps<{ examples: string[] }>()

defineEmits<{ select: [text: string] }>()
</script>

<style scoped lang="scss">
.ai-empty {
    text-align: center;
    padding: 40px 16px;
}

.ai-empty-title {
    font-size: 15px;
    font-weight: 600;
    color: #303133;
    margin: 0 0 8px;
}

.ai-empty-sub {
    font-size: 13px;
    color: #909399;
    margin: 0 0 20px;
}

.ai-examples {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: center;
}

.ai-example-tag {
    cursor: pointer;
    font-size: 12px;

    &:hover {
        color: #409eff;
        border-color: #409eff;
    }
}
</style>
