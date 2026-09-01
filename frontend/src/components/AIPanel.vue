<template>
    <div class="ai-panel" :class="{ visible: modelValue }">
        <div class="ai-panel-header">
            <span class="ai-panel-title">AI 助手</span>
            <div class="ai-panel-actions">
                <el-button
                    v-if="messages.length"
                    text
                    size="small"
                    @click="clearChat"
                >
                    清空对话
                </el-button>
                <el-button text :icon="Close" @click="$emit('update:modelValue', false)" />
            </div>
        </div>

        <div ref="chatBodyRef" class="ai-panel-body">
            <!-- 空状态提示 -->
            <AIEmptyState
                v-if="!messages.length"
                :examples="examples"
                @select="sendMessage"
            />

            <!-- 流式进度条（Agent 执行中展示） -->
            <AIStreamingProgress
                v-if="isStreaming"
                :steps="streamingSteps"
            />

            <!-- 对话消息 -->
            <div
                v-for="(msg, i) in messages"
                :key="i"
                class="ai-msg"
                :class="msg.role"
            >
                <div class="ai-msg-bubble">
                    <span v-if="msg.role === 'assistant' && msg.loading" class="ai-typing">
                        <span /><span /><span />
                        <span class="ai-typing-text">{{ loadingText }}</span>
                    </span>
                    <template v-else>
                        {{ msg.content }}
                    </template>
                </div>
                <!-- 快捷回复建议（ask_question 附带） -->
                <div v-if="msg.suggestions?.length && !msg.optionSelected" class="ai-suggestions">
                    <el-tag
                        v-for="s in msg.suggestions"
                        :key="s"
                        class="ai-suggestion-tag"
                        effect="plain"
                        @click="sendMessage(s)"
                    >
                        {{ s }}
                    </el-tag>
                </div>
                <!-- 选项卡片（propose_options） -->
                <AIOptionCards
                    v-if="msg.options?.length && !msg.optionSelected"
                    :options="msg.options"
                    @select="opt => selectOption(msg, opt)"
                />
                <!-- 方案确认卡片（confirm_plan） -->
                <AIPlanCard
                    v-if="msg.plan"
                    :plan="msg.plan"
                    :resolved="msg.planResolved"
                    @confirm="confirmPlan(msg)"
                    @reject="rejectPlan(msg)"
                />
            </div>
        </div>

        <!-- 图片上传预览区 -->
        <div v-if="uploadedImage" class="ai-image-preview">
            <img :src="uploadedImage" alt="参考图">
            <el-button text size="small" @click="uploadedImage = null">
                ✕ 移除
            </el-button>
        </div>
        <!-- 工具栏 -->
        <div class="ai-panel-toolbar">
            <el-upload
                :show-file-list="false"
                accept="image/*"
                :before-upload="handleImageUpload"
            >
                <el-button text size="small" title="上传参考图（海报/草图）">
                    📎 上传参考图
                </el-button>
            </el-upload>
        </div>
        <div class="ai-panel-footer">
            <el-input
                v-model="inputText"
                type="textarea"
                :rows="2"
                :placeholder="uploadedImage ? '描述你想要如何修改参考图...' : (hasComponents ? '继续说，比如「标题改大一点」' : '描述你想要的海报或报名表...')"
                :disabled="loading"
                @keydown.enter.prevent="sendMessage()"
                @keydown.shift.enter="(e: KeyboardEvent) => { /* Shift+Enter = 换行，默认行为 */ }"
            />
            <el-button
                type="primary"
                :loading="loading"
                :disabled="!inputText.trim()"
                class="ai-send-btn"
                @click="sendMessage()"
            >
                发送
            </el-button>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Close } from '@element-plus/icons-vue'
import AIEmptyState from './AI/AIEmptyState.vue'
import AIStreamingProgress from './AI/AIStreamingProgress.vue'
import AIOptionCards from './AI/AIOptionCards.vue'
import AIPlanCard from './AI/AIPlanCard.vue'
import { useAIChat } from '@/composables/useAIChat'

defineProps<{ modelValue: boolean }>()
defineEmits<{ 'update:modelValue': [value: boolean] }>()

const chatBodyRef = ref<HTMLElement>()
const {
    messages,
    loading,
    loadingText,
    inputText,
    uploadedImage,
    streamingSteps,
    isStreaming,
    hasComponents,
    sendMessage,
    clearChat,
    selectOption,
    confirmPlan,
    rejectPlan,
} = useAIChat(chatBodyRef)

const examples = [
    '街舞社招新海报，时间9月15日，地点大活',
    '志愿者报名表，含姓名学号学院意向部门',
    '读书分享会宣传海报，文艺清新风格',
    '社团纳新报名表，包含5个部门选择',
]

/** 上传图片：压缩到 1024px 以内，避免 token 爆炸 */
function handleImageUpload(file: File): false {
    const reader = new FileReader()
    reader.onload = () => {
        const img = new Image()
        img.onload = () => {
            const canvas = document.createElement('canvas')
            const scale = Math.min(1, 1024 / Math.max(img.width, img.height))
            canvas.width = Math.round(img.width * scale)
            canvas.height = Math.round(img.height * scale)
            canvas.getContext('2d')?.drawImage(img, 0, 0, canvas.width, canvas.height)
            uploadedImage.value = canvas.toDataURL('image/jpeg', 0.8)
        }
        img.src = reader.result as string
    }
    reader.readAsDataURL(file)
    return false
}
</script>

<style scoped lang="scss">
.ai-panel {
    position: fixed;
    top: 60px;
    right: -400px;
    width: 400px;
    height: calc(100vh - 60px);
    background: #fff;
    border-left: 1px solid #e4e7ed;
    box-shadow: -4px 0 12px rgba(0, 0, 0, 0.08);
    display: flex;
    flex-direction: column;
    z-index: 2000;
    transition: right 0.3s ease;

    &.visible {
        right: 0;
    }
}

.ai-panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    border-bottom: 1px solid #ebeef5;
}

.ai-panel-title {
    font-size: 15px;
    font-weight: 600;
    color: #303133;
}

.ai-panel-actions {
    display: flex;
    align-items: center;
    gap: 4px;
}

.ai-panel-body {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
}

.ai-msg {
    margin-bottom: 12px;
    display: flex;

    &.user {
        justify-content: flex-end;

        .ai-msg-bubble {
            background: #409eff;
            color: #fff;
            border-radius: 12px 12px 2px 12px;
        }
    }

    &.assistant {
        flex-direction: column;
        align-items: flex-start;

        .ai-msg-bubble {
            background: #f4f4f5;
            color: #303133;
            border-radius: 12px 12px 12px 2px;
        }
    }
}

.ai-msg-bubble {
    max-width: 85%;
    padding: 10px 14px;
    font-size: 13px;
    line-height: 1.6;
    word-break: break-word;
    white-space: pre-wrap;
}

.ai-typing {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 0;

    span {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: #909399;
        animation: typing 1.2s infinite;

        &:nth-child(2) { animation-delay: 0.2s; }
        &:nth-child(3) { animation-delay: 0.4s; }
    }

    .ai-typing-text {
        all: unset;
        font-size: 12px;
        color: #909399;
        margin-left: 4px;
        animation: none;
        width: auto;
        height: auto;
        border-radius: 0;
        background: none;
    }
}

@keyframes typing {
    0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
    30% { opacity: 1; transform: translateY(-4px); }
}

.ai-image-preview {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    border-top: 1px solid #ebeef5;
    background: #fafafa;

    img {
        max-height: 80px;
        max-width: 120px;
        border-radius: 6px;
        border: 1px solid #e4e7ed;
        object-fit: cover;
    }
}

.ai-panel-toolbar {
    display: flex;
    align-items: center;
    padding: 4px 16px;
    border-top: 1px solid #ebeef5;
    background: #fff;
}

.ai-panel-footer {
    padding: 12px 16px;
    border-top: 1px solid #ebeef5;
}

.ai-send-btn {
    width: 100%;
    margin-top: 8px;
}

.ai-suggestions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 8px;
}

.ai-suggestion-tag {
    cursor: pointer;
    font-size: 13px;
    padding: 6px 12px;
    border-radius: 16px;

    &:hover {
        color: #409eff;
        border-color: #409eff;
        background: #ecf5ff;
    }
}
</style>
