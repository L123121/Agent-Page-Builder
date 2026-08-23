<script setup lang="ts">
import { ref } from 'vue'
import AIPanel from '../AIPanel.vue'

// 测试宿主：模拟 Toolbar 中 `<AIPanel v-model="showAIPanel" />` 的用法
const showAIPanel = ref(false)

function toggleAI() {
    showAIPanel.value = !showAIPanel.value
}
</script>

<template>
    <div>
        <button id="ai-toggle-btn" @click="toggleAI">
            AI 生成
        </button>
        <AIPanel v-model="showAIPanel" />
    </div>
</template>
