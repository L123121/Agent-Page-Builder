/**
 * AI 页面生成 API 服务（LLM 自主决策）
 */
import axios from 'axios'
import type { ComponentData, CanvasStyleData } from '@/types'
import { getAccessToken } from '@/utils/auth'
import { withAuthInterceptors } from '@/utils/api'

export interface ChatMessage {
    role: 'user' | 'assistant'
    content: string
}

export interface AIAction {
    type: 'generate' | 'add' | 'modify' | 'delete' | 'move'
    components?: ComponentData[]
    canvasStyle?: CanvasStyleData
    component?: ComponentData
    id?: string
    style?: Record<string, unknown>
    propValue?: unknown
    top?: number
    left?: number
}

export interface AIOption {
    id: string
    title: string
    description: string
    tag?: string
}

export interface AIPlan {
    summary: string
    details: string[]
}

export interface AIChatResponse {
    reply: string
    actions: AIAction[]
    options?: AIOption[]
    question?: string
    suggestions?: string[]
    plan?: AIPlan
    nextStage?: AgentStage
    validation?: {
        valid: boolean
        errorCount: number
        warningCount: number
        summary: string
        issues: Array<Record<string, unknown>>
    }
    trace?: Array<Record<string, unknown>>
    /** 会话标识：同一 threadId 下的执行状态由服务端 checkpoint 持久化 */
    threadId?: string
    /** 为 true 表示图已挂起等待用户输入，下次请求需带 threadId + resume 恢复 */
    waitingForInput?: boolean
}

export type AgentStage = 'discover' | 'design' | 'plan' | 'confirm' | 'execute' | 'edit'

const api = axios.create({
    baseURL: import.meta.env.VITE_API_BASE || 'http://localhost:8000',
    timeout: 90000,
})

// AI 接口有真实 LLM 成本，后端强制鉴权：复用 Bearer 注入 + 401 静默刷新
withAuthInterceptors(api)

/**
 * AI 对话：LLM 自主决策使用哪个工具
 */
export async function chatWithAI(params: {
    prompt: string
    history: ChatMessage[]
    components: ComponentData[]
    canvasStyle: CanvasStyleData
    canvasWidth?: number
    canvasHeight?: number
    selectedComponentIds?: string[]
    viewport?: {
        width: number
        height: number
        scale: number
    }
    projectKnowledge?: string
    conversationStage?: AgentStage
    /** 会话标识：首次留空由服务端生成，收到 waitingForInput=true 后必须带回 */
    threadId?: string
    /** 中断恢复数据：上次响应 waitingForInput=true 时，把用户本轮输入作为 resume 传回 */
    resume?: unknown
    /** 参考图 data URL (image/...)，仅首轮携带，发送后前端清空 */
    image?: string
    signal?: AbortSignal
}): Promise<AIChatResponse> {
    const { signal, ...rest } = params
    const { data } = await api.post<AIChatResponse>('/api/ai/chat', rest, { signal })
    return data
}

// ==================== 流式请求（SSE） ====================

/** SSE 流式事件类型 */
export interface StreamEvent {
    type: 'agent_start' | 'tool_call' | 'tool_result' | 'self_correction' | 'agent_done' | 'agent_error'
    stage?: AgentStage
    step?: number
    tool?: string
    status?: 'done' | 'waiting_for_user'
    args?: Record<string, unknown>
    /** self_correction：反馈触发的自省修正轮次（tool_not_allowed / unresolved_component_ref 等） */
    error?: string
    detail?: Record<string, unknown>
    validation?: AIChatResponse['validation']
    autoFixes?: Array<Record<string, unknown>>
    options?: AIOption[]
    question?: string
    suggestions?: string[]
    plan?: AIPlan
    threadId?: string
    result?: AIChatResponse
}

/** 流式请求参数（与 chatWithAI 基本一致，去掉 signal，改用 onEvent 回调） */
export interface ChatStreamParams {
    prompt: string
    history: ChatMessage[]
    components: ComponentData[]
    canvasStyle: CanvasStyleData
    canvasWidth?: number
    canvasHeight?: number
    selectedComponentIds?: string[]
    viewport?: {
        width: number
        height: number
        scale: number
    }
    projectKnowledge?: string
    conversationStage?: AgentStage
    threadId?: string
    image?: string
}

/**
 * 流式 AI 对话 — 逐行解析 SSE，实时回调进度事件
 * @param params 请求参数
 * @param onEvent 每收到一个事件就回调一次
 * @returns 最终完整响应（agent_done 时的 result）
 */
export async function chatWithAIStream(
    params: ChatStreamParams,
    onEvent: (event: StreamEvent) => void,
): Promise<AIChatResponse | null> {
    const baseURL = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
    const response = await fetch(`${baseURL}/api/ai/chat/stream`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
        },
        body: JSON.stringify(params),
    })

    if (!response.body) {
        throw new Error('Response body is null')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finalResult: AIChatResponse | null = null

    // SSE 读取循环：没有固定次数，读到 done 为止
    // eslint-disable-next-line no-constant-condition
    while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // 按 \n\n 分割 SSE 事件
        const chunks = buffer.split('\n\n')
        buffer = chunks.pop() || ''

        for (const chunk of chunks) {
            const line = chunk.trim()
            if (!line || !line.startsWith('data: ') || line === 'data: [DONE]') continue

            try {
                const event = JSON.parse(line.slice(6)) as StreamEvent
                onEvent(event)

                // 收集最终结果
                if (event.type === 'agent_done' && event.result) {
                    finalResult = event.result
                }
            } catch {
                // 忽略解析失败的行
            }
        }
    }

    return finalResult
}
