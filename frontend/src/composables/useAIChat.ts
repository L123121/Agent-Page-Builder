/**
 * AI 对话状态机 — 消息流、阶段跟踪、服务端会话（threadId/resume）、
 * localStorage 持久化与 SSE 流式进度。
 *
 * 与服务端的协作协议：
 * - conversationStage：上一轮响应的 nextStage，随请求回传（确定性路由的输入之一）；
 * - threadId：服务端 checkpointer 会话标识，waitingForInput=true 挂起后
 *   凭它恢复图执行；
 * - 持久化版本号 HISTORY_VERSION：消息结构变更时 +1，旧结构自动清空。
 */
import { ref, computed, nextTick, watch, onMounted, type Ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { chatWithAIStream, type ChatMessage, type AIOption, type AIPlan, type AgentStage, type StreamEvent } from '@/api/ai'
import { useStore } from '@/store'
import { useAIActions } from '@/composables/useAIActions'

export interface DisplayMessage {
    role: 'user' | 'assistant'
    content: string
    loading?: boolean
    options?: AIOption[]
    optionSelected?: string
    suggestions?: string[]
    plan?: AIPlan
    planResolved?: boolean
}

export interface StreamingStep {
    step: number
    tool: string
    status: 'pending' | 'running' | 'done' | 'error'
    /** 自省修正轮次（tool_not_allowed / unresolved_component_ref 等反馈后的重试） */
    correction?: boolean
    correctionError?: string
    validation?: { valid: boolean; errorCount: number; warningCount: number }
    autoFixes?: Array<Record<string, unknown>>
}

const VALID_STAGES: AgentStage[] = ['discover', 'design', 'plan', 'confirm', 'execute', 'edit']

const HISTORY_KEY = 'ai-chat-history'
const HISTORY_STAGE_KEY = 'ai-chat-stage'
const HISTORY_VERSION_KEY = 'ai-chat-version'
const HISTORY_THREAD_KEY = 'ai-chat-thread-id'
const HISTORY_VERSION = '4'

export function useAIChat(chatBodyRef: Ref<HTMLElement | undefined>) {
    const store = useStore()
    const { applyAIActions } = useAIActions()

    const loading = ref(false)
    const loadingText = ref('AI 正在思考...')
    const inputText = ref('')
    const messages = ref<DisplayMessage[]>([])
    const conversationStage = ref<AgentStage>('discover')
    /** 上传的参考图 data URL，仅首轮携带 */
    const uploadedImage = ref<string | null>(null)
    const streamingSteps = ref<StreamingStep[]>([])
    const isStreaming = ref(false)

    /** 服务端会话标识：同一 threadId 下的执行状态由 checkpoint 持久化，可中断恢复 */
    const aiThreadId = ref<string | null>(localStorage.getItem(HISTORY_THREAD_KEY))
    /** 上一次响应 waitingForInput=true 时置位，下次请求需带 resume 恢复图执行 */
    const waitingForInput = ref(false)

    const hasComponents = computed(() => store.componentData.length > 0)
    const selectedComponentIds = computed(() => {
        const areaIds = store.areaData.components.map(component => component.id)
        if (areaIds.length > 0) return areaIds
        return store.curComponent ? [store.curComponent.id] : []
    })

    // ==================== 持久化 ====================

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
                messages.value = JSON.parse(raw) as DisplayMessage[]
            }
            const savedStage = localStorage.getItem(HISTORY_STAGE_KEY) as AgentStage | null
            if (savedStage && VALID_STAGES.includes(savedStage)) {
                conversationStage.value = savedStage
            }
            // 恢复会话时同时恢复服务端 threadId（checkpoint 持久化）
            const savedThread = localStorage.getItem(HISTORY_THREAD_KEY)
            if (savedThread) {
                aiThreadId.value = savedThread
            }
        } catch { /* ignore */ }
    }

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

    // ==================== 流式事件 → 进度步骤 ====================

    function handleStreamEvent(event: StreamEvent) {
        if (event.type === 'tool_call') {
            streamingSteps.value.push({
                step: event.step ?? streamingSteps.value.length + 1,
                tool: event.tool || '',
                status: 'running',
            })
        } else if (event.type === 'self_correction') {
            streamingSteps.value.push({
                step: event.step ?? streamingSteps.value.length + 1,
                tool: 'self_correction',
                status: 'done',
                correction: true,
                correctionError: event.error,
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
    }

    // ==================== 发送 ====================

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
            }, handleStreamEvent)

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
                applyAIActions(res.actions)
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

    return {
        // 状态
        messages,
        loading,
        loadingText,
        inputText,
        conversationStage,
        uploadedImage,
        streamingSteps,
        isStreaming,
        hasComponents,
        // 动作
        sendMessage,
        clearChat,
        selectOption,
        confirmPlan,
        rejectPlan,
    }
}
