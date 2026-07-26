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
}

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
    signal?: AbortSignal
}): Promise<AIChatResponse> {
    const { signal, ...rest } = params
    const { data } = await api.post<AIChatResponse>('/api/ai/chat', rest, { signal })
    return data
}