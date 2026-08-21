<template>
    <div class="ai-panel" :class="{ visible: modelValue }">
        <div class="ai-panel-header">
            <span class="ai-panel-title">AI 助手</span>
            <div class="ai-panel-actions">
                <el-button v-if="messages.length" text size="small" @click="clearChat">
                    清空对话
                </el-button>
                <el-button text :icon="Close" @click="$emit('update:modelValue', false)" />
            </div>
        </div>

        <div ref="chatBodyRef" class="ai-panel-body">
            <!-- 空状态提示 -->
            <div v-if="!messages.length" class="ai-empty">
                <p class="ai-empty-title">描述你想要的页面，AI 帮你生成</p>
                <p class="ai-empty-sub">一步步引导你完成设计，生成后可以自由修改</p>
                <div class="ai-examples">
                    <el-tag
                        v-for="ex in examples"
                        :key="ex"
                        class="ai-example-tag"
                        effect="plain"
                        @click="sendMessage(ex)"
                    >
                        {{ ex }}
                    </el-tag>
                </div>
            </div>

            <!-- 流式进度条（Agent 执行中展示） -->
            <div v-if="isStreaming" class="ai-streaming">
                <div class="ai-streaming-header">
                    <span class="ai-streaming-dot" />
                    <span>Agent 执行中 · 第 {{ streamingSteps.length }} 步</span>
                </div>
                <div
                    v-for="step in streamingSteps"
                    :key="step.step"
                    class="ai-streaming-step"
                    :class="step.status"
                >
                    <span class="step-icon">
                        {{ step.status === 'done' ? '✅' :
                           step.status === 'error' ? '❌' :
                           step.status === 'running' ? '⏳' : '⏸' }}
                    </span>
                    <span class="step-tool">{{ toolLabels[step.tool] || step.tool }}</span>
                    <span v-if="step.autoFixes?.length" class="step-fixes">
                        修复 {{ step.autoFixes.length }} 项
                    </span>
                    <span v-if="step.validation && !step.validation.valid" class="step-warn">
                        {{ step.validation.errorCount }} 错误
                    </span>
                </div>
            </div>

            <!-- 对话消息 -->
            <div v-for="(msg, i) in messages" :key="i" class="ai-msg" :class="msg.role">
                <div class="ai-msg-bubble">
                    <span v-if="msg.role === 'assistant' && msg.loading" class="ai-typing">
                        <span /><span /><span />
                        <span class="ai-typing-text">{{ loadingText }}</span>
                    </span>
                    <template v-else>{{ msg.content }}</template>
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
                <div v-if="msg.options?.length && !msg.optionSelected" class="ai-options">
                    <div
                        v-for="opt in msg.options"
                        :key="opt.id"
                        class="ai-option-card"
                        :class="{ disabled: msg.optionSelected }"
                        @click="selectOption(msg, opt)"
                    >
                        <div class="ai-option-header">
                            <span class="ai-option-title">{{ opt.title }}</span>
                            <el-tag v-if="opt.tag" size="small" type="warning" effect="plain">
                                {{ opt.tag }}
                            </el-tag>
                        </div>
                        <p class="ai-option-desc">{{ opt.description }}</p>
                    </div>
                </div>
                <!-- 方案确认卡片（confirm_plan） -->
                <div v-if="msg.plan" class="ai-plan" :class="{ disabled: msg.planResolved }">
                    <p class="ai-plan-summary">{{ msg.plan.summary }}</p>
                    <ul class="ai-plan-details">
                        <li v-for="(d, j) in msg.plan.details" :key="j">{{ d }}</li>
                    </ul>
                    <div v-if="!msg.planResolved" class="ai-plan-actions">
                        <el-button type="primary" size="small" @click="confirmPlan(msg)">
                            确认生成
                        </el-button>
                        <el-button size="small" @click="rejectPlan(msg)">
                            我要修改
                        </el-button>
                    </div>
                </div>
            </div>
        </div>

        <!-- 图片上传预览区 -->
        <div v-if="uploadedImage" class="ai-image-preview">
            <img :src="uploadedImage" alt="参考图" />
            <el-button text size="small" @click="removeImage">✕ 移除</el-button>
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
                @keydown.enter.prevent="handleSend"
                @keydown.shift.enter="(e: KeyboardEvent) => { /* Shift+Enter = 换行，默认行为 */ }"
            />
            <el-button
                type="primary"
                :loading="loading"
                :disabled="!inputText.trim()"
                class="ai-send-btn"
                @click="handleSend"
            >
                发送
            </el-button>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { chatWithAI, chatWithAIStream, type ChatMessage, type AIAction, type AIOption, type AIPlan, type AgentStage, type StreamEvent } from '@/api/ai'
import { useStore } from '@/store'
import {
    importDataWithCommand,
    addComponentWithCommand,
    deleteComponentWithCommand,
} from '@/composables/useCommandActions'
import { deepCopy } from '@/utils/utils'
import type { ComponentData } from '@/types'

defineProps<{ modelValue: boolean }>()
defineEmits<{ 'update:modelValue': [value: boolean] }>()

const store = useStore()
const inputText = ref('')
const loading = ref(false)
const loadingText = ref('AI 正在思考...')
const chatBodyRef = ref<HTMLElement>()
const AI_TIMEOUT = 90000 // 90 秒超时

// 前端请求取消 token，用于超时真正中断 fetch
let currentAbortController: AbortController | null = null

interface DisplayMessage {
    role: 'user' | 'assistant'
    content: string
    loading?: boolean
    options?: AIOption[]
    optionSelected?: string
    suggestions?: string[]
    plan?: AIPlan
    planResolved?: boolean
}
const messages = ref<DisplayMessage[]>([])
const conversationStage = ref<AgentStage>('discover')
/** 上传的参考图 data URL，仅首轮携带 */
const uploadedImage = ref<string | null>(null)

// ==================== 流式进度状态 ====================
interface StreamingStep {
    step: number
    tool: string
    status: 'pending' | 'running' | 'done' | 'error'
    validation?: { valid: boolean; errorCount: number; warningCount: number }
    autoFixes?: Array<Record<string, unknown>>
}
const streamingSteps = ref<StreamingStep[]>([])
const isStreaming = ref(false)

/** 工具名 → 中文标签 */
const toolLabels: Record<string, string> = {
    propose_options: '生成选项',
    ask_question: '提出问题',
    confirm_plan: '确认方案',
    generate_page: '生成页面',
    edit_page: '修改页面',
    finish: '完成',
}

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

function removeImage() { uploadedImage.value = null }

const hasComponents = computed(() => store.componentData.length > 0)
const selectedComponentIds = computed(() => {
    const areaIds = store.areaData.components.map(component => component.id)
    if (areaIds.length > 0) return areaIds
    return store.curComponent ? [store.curComponent.id] : []
})

const examples = [
    '街舞社招新海报，时间9月15日，地点大活',
    '志愿者报名表，含姓名学号学院意向部门',
    '读书分享会宣传海报，文艺清新风格',
    '社团纳新报名表，包含5个部门选择',
]

// ==================== 对话历史持久化 ====================
const HISTORY_KEY = 'ai-chat-history'
const HISTORY_STAGE_KEY = 'ai-chat-stage'
const HISTORY_VERSION_KEY = 'ai-chat-version'
const HISTORY_THREAD_KEY = 'ai-chat-thread-id'
const HISTORY_VERSION = '4'

/** 服务端会话标识：同一 threadId 下的执行状态由 checkpoint 持久化，可中断恢复 */
const aiThreadId = ref<string | null>(localStorage.getItem(HISTORY_THREAD_KEY))
/** 上一次响应 waitingForInput=true 时置位，下次请求需带 resume 恢复图执行 */
const waitingForInput = ref(false)

function saveHistory() {
    try {
        const data = messages.value.map(m => ({
            role: m.role,
            content: m.content,
            options: m.options,
            optionSelected: m.optionSelected,
            suggestions: m.suggestions,
            plan: m.plan,
            planResolved: m.planResolved,
        }))
        localStorage.setItem(HISTORY_KEY, JSON.stringify(data))
        localStorage.setItem(HISTORY_STAGE_KEY, conversationStage.value)
        localStorage.setItem(HISTORY_VERSION_KEY, HISTORY_VERSION)
    } catch { /* quota exceeded */ }
}

function loadHistory() {
    try {
        if (localStorage.getItem(HISTORY_VERSION_KEY) !== HISTORY_VERSION) {
            localStorage.removeItem(HISTORY_KEY)
            localStorage.removeItem(HISTORY_STAGE_KEY)
            localStorage.removeItem(HISTORY_THREAD_KEY)
            localStorage.setItem(HISTORY_VERSION_KEY, HISTORY_VERSION)
            return
        }
        const raw = localStorage.getItem(HISTORY_KEY)
        if (raw) {
            const data = JSON.parse(raw) as DisplayMessage[]
            messages.value = data
        }
        const savedStage = localStorage.getItem(HISTORY_STAGE_KEY) as AgentStage | null
        if (savedStage && ['discover', 'design', 'plan', 'confirm', 'execute', 'edit'].includes(savedStage)) {
            conversationStage.value = savedStage
        }
        // 恢复会话时同时恢复服务端 threadId（checkpoint 持久化）
        const savedThread = localStorage.getItem(HISTORY_THREAD_KEY)
        if (savedThread) {
            aiThreadId.value = savedThread
        }
    } catch { /* ignore */ }
}

onMounted(() => {
    loadHistory()
})

// 自动滚动到底部 + 持久化
watch(messages, async () => {
    await nextTick()
    if (chatBodyRef.value) {
        chatBodyRef.value.scrollTop = chatBodyRef.value.scrollHeight
    }
    saveHistory()
}, { deep: true })

function clearChat() {
    messages.value = []
    conversationStage.value = 'discover'
    aiThreadId.value = null
    waitingForInput.value = false
    localStorage.removeItem(HISTORY_KEY)
    localStorage.removeItem(HISTORY_STAGE_KEY)
    localStorage.removeItem(HISTORY_THREAD_KEY)
    localStorage.setItem(HISTORY_VERSION_KEY, HISTORY_VERSION)
}

async function sendMessage(text?: string) {
    const prompt = (text || inputText.value).trim()
    if (!prompt || loading.value) return

    // AI 生成前检查画布是否已有内容
    const hasCanvasContent = store.componentData.length > 0
    const isFirstGenerate = messages.value.some(m => m.planResolved)
    if (hasCanvasContent && !isFirstGenerate && prompt.includes('确认') && prompt.includes('生成')) {
        try {
            await ElMessageBox.confirm('AI 将替换当前画布所有内容，是否继续？', '确认覆盖', {
                confirmButtonText: '继续', cancelButtonText: '取消', type: 'warning',
            })
        } catch { return }
    }

    inputText.value = ''
    messages.value.push({ role: 'user', content: prompt })
    messages.value.push({ role: 'assistant', content: '', loading: true })
    loading.value = true
    loadingText.value = 'AI 正在思考...'

    // 初始化流式进度
    streamingSteps.value = []
    isStreaming.value = true

    try {
        // 构建对话历史（不含 loading 占位）
        const history: ChatMessage[] = messages.value
            .filter(m => !m.loading)
            .slice(0, -1)
            .map(m => ({ role: m.role, content: m.content }))

        // 流式调用：逐事件更新进度
        const res = await chatWithAIStream({
            prompt,
            history,
            components: store.componentData,
            canvasStyle: store.canvasStyleData,
            canvasWidth: store.canvasStyleData.width,
            canvasHeight: store.canvasStyleData.height,
            selectedComponentIds: selectedComponentIds.value,
            viewport: {
                width: store.editor?.clientWidth || store.canvasStyleData.width,
                height: store.editor?.clientHeight || store.canvasStyleData.height,
                scale: store.canvasStyleData.scale,
            },
            projectKnowledge: `页面名称：${store.currentPageTitle}。优先复用当前组件结构，遵守现有画布尺寸和视觉风格。`,
            conversationStage: conversationStage.value,
            threadId: aiThreadId.value || undefined,
            image: uploadedImage.value || undefined,
        }, (event: StreamEvent) => {
            // 每收到一个事件，更新流式进度 UI
            if (event.type === 'tool_call') {
                streamingSteps.value.push({
                    step: event.step ?? streamingSteps.value.length + 1,
                    tool: event.tool || '',
                    status: 'running',
                })
            } else if (event.type === 'tool_result') {
                const step = streamingSteps.value.find(s => s.step === event.step)
                if (step) {
                    step.status = event.status === 'done' ? 'done' : 'error'
                    step.validation = event.validation
                    step.autoFixes = event.autoFixes
                }
            } else if (event.type === 'agent_error') {
                const lastMsg = messages.value[messages.value.length - 1]
                if (lastMsg) {
                    lastMsg.content = `出错了: ${event.error || '未知错误'}`
                }
            }
        })

        // 发送后清空参考图（仅首轮携带，后续多轮不带）
        uploadedImage.value = null
        isStreaming.value = false

        if (!res) {
            // 无结果（异常中断）
            const lastMsg = messages.value[messages.value.length - 1]
            lastMsg.loading = false
            if (!lastMsg.content) lastMsg.content = 'AI 处理中断，请重试'
            return
        }

        // 更新 AI 回复
        const lastMsg = messages.value[messages.value.length - 1]
        lastMsg.loading = false
        lastMsg.content = res.reply || '已完成修改'
        if (res.nextStage) {
            conversationStage.value = res.nextStage
        }
        if (res.validation) {
            lastMsg.content += `\n验证结果：${res.validation.summary}`
        }

        // 服务端 checkpoint 会话标识：首次返回后保存，后续恢复执行使用
        if (res.threadId) {
            aiThreadId.value = res.threadId
            localStorage.setItem(HISTORY_THREAD_KEY, res.threadId)
        }
        // 图挂起等待用户输入：置位后下次请求自动携带 resume
        waitingForInput.value = !!res.waitingForInput

        // 根据返回结果展示对应 UI
        if (res.options?.length) {
            lastMsg.options = res.options
        } else if (res.plan) {
            lastMsg.plan = res.plan
        } else if (res.suggestions?.length) {
            lastMsg.suggestions = res.suggestions
        } else if (res.actions.length > 0) {
            applyActions(res.actions)
            ElMessage.success(res.reply || '已完成')
        }
    } catch (err: unknown) {
        const lastMsg = messages.value[messages.value.length - 1]
        lastMsg.loading = false
        const error = err as { response?: { data?: { error?: string } }; message?: string }
        if (lastMsg && lastMsg.content === '') {
            lastMsg.content = '出错了: ' + (error?.response?.data?.error || error?.message || '未知错误')
        }
        ElMessage.error(lastMsg?.content || '请求失败')
    } finally {
        loading.value = false
        isStreaming.value = false
    }
}

function handleSend() {
    sendMessage()
}

/** 用户点击选项卡片 → 发送选择消息，LLM 自主决定下一步 */
function selectOption(msg: DisplayMessage, opt: AIOption) {
    if (msg.optionSelected || loading.value) return
    msg.optionSelected = opt.id
    sendMessage(`我选择「${opt.title}」`)
}

/** 用户确认方案 → 发送确认消息 */
function confirmPlan(msg: DisplayMessage) {
    if (msg.planResolved || loading.value) return
    msg.planResolved = true
    sendMessage('确认，请生成')
}

/** 用户要修改方案 → 发送修改意图 */
function rejectPlan(msg: DisplayMessage) {
    if (msg.planResolved || loading.value) return
    msg.planResolved = true
    sendMessage('我想修改一下方案')
}

// ==================== 组件查找与操作执行 ====================

function findComponent(id: string): ComponentData | undefined {
    const exact = store.componentData.find(c => c.id === id)
    if (exact) return exact

    const lower = id.toLowerCase()
    return store.componentData.find(c => {
        const pv = typeof c.propValue === 'string' ? c.propValue.toLowerCase() : ''
        const label = (c.label || '').toLowerCase()
        if (lower.includes('title') || lower.includes('标题')) {
            return c.component === 'VText' && (c.style.fontSize ?? 0) >= 20
        }
        if (lower.includes('bg') || lower.includes('背景')) {
            return c.component === 'RectShape' && (c.zIndex ?? 0) <= 5
        }
        if (lower.includes('btn') || lower.includes('button') || lower.includes('按钮')) {
            return c.component === 'VButton'
        }
        if (lower.includes('table') || lower.includes('表')) {
            return c.component === 'VTable'
        }
        if (pv && lower.includes(pv.slice(0, 6))) return true
        if (label && lower.includes(label)) return true
        return false
    })
}

function applyActions(actions: AIAction[]) {
    // 将 modify/move 批量处理为一次可撤销的整体替换（利用 ImportDataCommand）
    const modifyMoveActions = actions.filter(a => a.type === 'modify' || a.type === 'move')
    const otherActions = actions.filter(a => !['modify', 'move'].includes(a.type))

    if (modifyMoveActions.length > 0) {
        const allComponents = deepCopy(store.componentData)

        for (const action of modifyMoveActions) {
            const comp = allComponents.find(c => c.id === action.id)
            if (!comp) continue
            if (action.type === 'modify') {
                if (action.style) Object.assign(comp.style, action.style)
                if (action.propValue !== undefined) {
                    comp.propValue = action.propValue as ComponentData['propValue']
                }
            } else if (action.type === 'move') {
                if (action.top !== undefined) comp.style.top = action.top
                if (action.left !== undefined) comp.style.left = action.left
            }
        }

        importDataWithCommand(allComponents)
    }

    for (const action of otherActions) {
        switch (action.type) {
            case 'generate':
                if (action.components?.length) {
                    importDataWithCommand(action.components as ComponentData[], action.canvasStyle)
                }
                break
            case 'add':
                if (action.component) {
                    addComponentWithCommand(action.component as ComponentData)
                }
                break
            case 'delete': {
                const comp = action.id ? findComponent(action.id) : undefined
                if (comp) deleteComponentWithCommand(comp.id)
                break
            }
        }
    }
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

// ==================== 流式进度 UI ====================

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
