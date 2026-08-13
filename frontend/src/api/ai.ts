/**
 * AI 页面生成 API 服务（LLM 自主决策）
 */
import axios from 'axios'
import type { ComponentData, CanvasStyleData } from '@/types'

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
    signal?: AbortSignal
}): Promise<AIChatResponse> {
    const { signal, ...rest } = params
    const { data } = await api.post<AIChatResponse>('/api/ai/chat', rest, { signal })
    return data
}
