/**
 * 认证状态与 token 管理 — access/refresh 双 token + 登录态
 *
 * 存储取舍（面试考点）：token 存 localStorage 会暴露给 XSS、存 HttpOnly
 * cookie 会引入 CSRF。本项目选 localStorage + Bearer header（无 cookie，
 * 免 CSRF），配合后端工具白名单 + 输入清洗缓解 XSS；token 短有效期（30min）
 * + refresh 轮换（7d）限制泄露窗口。
 */

import { reactive } from 'vue'
import eventBus from '@/utils/eventBus'

const ACCESS_KEY = 'auth-access-token'
const REFRESH_KEY = 'auth-refresh-token'
const USER_KEY = 'auth-username'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

export interface AuthTokens {
    accessToken: string
    refreshToken: string
    username: string
}

/** 全局登录态：LoginDialog 与各处 UI 响应式绑定 */
export const authState = reactive({
    accessToken: localStorage.getItem(ACCESS_KEY) || '',
    refreshToken: localStorage.getItem(REFRESH_KEY) || '',
    username: localStorage.getItem(USER_KEY) || '',
    /** 登录对话框显隐（401 时由拦截器置位） */
    showLogin: false,
})

export function isAuthenticated(): boolean {
    return !!authState.accessToken
}

export function getAccessToken(): string {
    return authState.accessToken
}

export function setTokens(tokens: AuthTokens): void {
    authState.accessToken = tokens.accessToken
    authState.refreshToken = tokens.refreshToken
    authState.username = tokens.username
    localStorage.setItem(ACCESS_KEY, tokens.accessToken)
    localStorage.setItem(REFRESH_KEY, tokens.refreshToken)
    localStorage.setItem(USER_KEY, tokens.username)
    eventBus.emit('auth:login')
}

export function clearTokens(): void {
    authState.accessToken = ''
    authState.refreshToken = ''
    authState.username = ''
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
    localStorage.removeItem(USER_KEY)
}

async function authRequest(path: string, body: Record<string, string>): Promise<AuthTokens> {
    const resp = await fetch(`${API_BASE}/api/auth/${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) {
        throw new Error(data.detail || '认证失败')
    }
    const tokens = data as AuthTokens
    setTokens(tokens)
    return tokens
}

export async function authLogin(username: string, password: string): Promise<AuthTokens> {
    return authRequest('login', { username, password })
}

export async function authRegister(username: string, password: string): Promise<AuthTokens> {
    return authRequest('register', { username, password })
}

export function authLogout(): void {
    clearTokens()
}

/**
 * 静默刷新：用 refreshToken 换新双 token。
 * 成功返回 true（调用方重试原请求）；失败清空登录态并弹出登录框。
 */
export async function tryRefreshToken(): Promise<boolean> {
    if (!authState.refreshToken) return false
    try {
        const resp = await fetch(`${API_BASE}/api/auth/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refreshToken: authState.refreshToken }),
        })
        if (!resp.ok) {
            clearTokens()
            authState.showLogin = true
            return false
        }
        const tokens = (await resp.json()) as AuthTokens
        // 静默刷新不 emit auth:login（不打扰页面列表刷新逻辑）
        authState.accessToken = tokens.accessToken
        authState.refreshToken = tokens.refreshToken
        authState.username = tokens.username
        localStorage.setItem(ACCESS_KEY, tokens.accessToken)
        localStorage.setItem(REFRESH_KEY, tokens.refreshToken)
        localStorage.setItem(USER_KEY, tokens.username)
        return true
    } catch {
        return false
    }
}

/** 打开登录对话框（由 401 拦截或入口按钮触发） */
export function requireLogin(): void {
    authState.showLogin = true
}
