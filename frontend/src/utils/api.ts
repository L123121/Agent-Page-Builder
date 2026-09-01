/**
 * API 请求封装 — JWT Bearer 鉴权 + 401 静默刷新
 */

import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import type { ComponentData, CanvasStyleData } from '@/types'
import { getAccessToken, requireLogin, tryRefreshToken } from '@/utils/auth'

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

export interface PageVersionSummary {
    _id: string
    pageId: string
    name: string
    description: string
    createdAt: string
}

export interface PageVersionInfo extends PageVersionSummary {
    componentData: ComponentData[]
    canvasStyle: CanvasStyleData
}

export interface PageVersionPayload {
    name: string
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

// 并发 401 时只发一次刷新，其余等待后直接用新 token 重试
let refreshPromise: Promise<boolean> | null = null

function refreshSingleFlight(): Promise<boolean> {
    if (!refreshPromise) {
        refreshPromise = tryRefreshToken().finally(() => {
            refreshPromise = null
        })
    }
    return refreshPromise
}

/**
 * 给 axios 实例装上鉴权拦截器：请求注入 Bearer；
 * 401 时单飞刷新并重试一次原请求，刷新失败弹登录框。
 * 供 pages 主实例与 AI 实例共用（不改动成功响应的形态）。
 */
export function withAuthInterceptors(instance: AxiosInstance): void {
    instance.interceptors.request.use((config) => {
        const token = getAccessToken()
        if (token) config.headers.Authorization = `Bearer ${token}`
        return config
    })
    instance.interceptors.response.use(undefined, async (error) => {
        const config = error.config as (AxiosRequestConfig & { _retried?: boolean }) | undefined
        const status = error.response?.status
        const url = String(error.config?.url || '')
        if (status === 401 && config && !config._retried && !url.includes('/api/auth/')) {
            config._retried = true
            if (await refreshSingleFlight()) {
                config.headers = config.headers ?? {}
                config.headers.Authorization = `Bearer ${getAccessToken()}`
                return instance.request(config)
            }
        } else if (status === 401) {
            requireLogin()
        }
        const msg = error.response?.data?.error || error.response?.data?.detail || '请求失败'
        return Promise.reject(new Error(msg))
    })
}

withAuthInterceptors(api)

api.interceptors.response.use((response) => response.data)

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
    listVersions(pageId: string) {
        return api.get(`/api/pages/${pageId}/versions`) as Promise<{ versions: PageVersionSummary[] }>
    },
    createVersion(pageId: string, data: PageVersionPayload) {
        return api.post(`/api/pages/${pageId}/versions`, data) as Promise<{ version: PageVersionInfo }>
    },
    getVersion(pageId: string, versionId: string) {
        return api.get(`/api/pages/${pageId}/versions/${versionId}`) as Promise<{ version: PageVersionInfo }>
    },
    deleteVersion(pageId: string, versionId: string) {
        return api.delete(`/api/pages/${pageId}/versions/${versionId}`) as Promise<{ message: string }>
    },
}

export default api
