/**
 * API 请求封装 — 无认证模式
 */

import axios from 'axios'
import type { ComponentData, CanvasStyleData } from '@/types'

export interface PageInfo {
    _id: string
    title: string
    description?: string
    userId?: string
    componentData: ComponentData[]
    canvasStyle: CanvasStyleData
    shareToken?: string | null
    isPublic: boolean
    createdAt: string
    updatedAt: string
}

export type PageSummary = Pick<PageInfo, '_id' | 'title' | 'description' | 'createdAt' | 'updatedAt' | 'isPublic'>

export interface PagePayload {
    title?: string
    description?: string
    componentData?: ComponentData[]
    canvasStyle?: CanvasStyleData
}

export function getErrorMessage(error: unknown, fallback = '请求失败'): string {
    if (error instanceof Error) return error.message
    if (typeof error === 'string') return error
    return fallback
}

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const api = axios.create({
    baseURL: API_BASE,
    timeout: 15000,
    headers: { 'Content-Type': 'application/json' },
})

api.interceptors.response.use(
    (response) => response.data,
    (error) => {
        const msg = error.response?.data?.error || error.response?.data?.detail || '请求失败'
        return Promise.reject(new Error(msg))
    },
)

export const pagesApi = {
    list() {
        return api.get('/api/pages') as Promise<{ pages: PageSummary[] }>
    },
    get(id: string) {
        return api.get(`/api/pages/${id}`) as Promise<{ page: PageInfo }>
    },
    create(data: PagePayload) {
        return api.post('/api/pages', data) as Promise<{ page: PageInfo }>
    },
    update(id: string, data: PagePayload) {
        return api.put(`/api/pages/${id}`, data) as Promise<{ page: PageInfo }>
    },
    delete(id: string) {
        return api.delete(`/api/pages/${id}`) as Promise<{ message: string }>
    },
    share(id: string) {
        return api.post(`/api/pages/${id}/share`) as Promise<{ shareToken: string; shareUrl: string }>
    },
    unshare(id: string) {
        return api.delete(`/api/pages/${id}/share`) as Promise<{ message: string }>
    },
}

export default api