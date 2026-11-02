import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import axios, { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { withAuthInterceptors } from '@/utils/api'
import { authState, tryRefreshToken } from '@/utils/auth'

function loginAs(username: string): void {
    authState.username = username
    authState.accessToken = `${username}-access`
    authState.refreshToken = `${username}-refresh`
    authState.showLogin = false
}

function deferred<T>() {
    let resolve!: (value: T) => void
    let reject!: (reason: Error) => void
    const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
    return { promise, resolve, reject }
}

beforeEach(() => {
    localStorage.clear()
    loginAs('alice')
    vi.stubGlobal('fetch', vi.fn())
})
afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
})

describe('请求账号绑定', () => {
    it('请求实际发送前切换账号时，不使用新账号提交旧页面数据', async () => {
        const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => ({
            config, data: {}, status: 200, statusText: 'OK', headers: {},
        }))
        const client = axios.create({ adapter })
        withAuthInterceptors(client)
        const config = { headers: {}, authOwner: 'user:alice' }
        const saving = client.post('/api/pages', { title: 'Alice page' }, config)
        loginAs('bob')
        await expect(saving).rejects.toThrow()
        expect(adapter).not.toHaveBeenCalled()
        expect(fetch).not.toHaveBeenCalled()
    })

    it('旧账号的 401 响应不会刷新新账号 token 或重放请求', async () => {
        const response = deferred<AxiosResponse>()
        const adapter = vi.fn((_config: InternalAxiosRequestConfig) => response.promise)
        const client = axios.create({ adapter })
        withAuthInterceptors(client)
        const saving = client.put('/api/pages/A', {})
        await vi.waitFor(() => expect(adapter).toHaveBeenCalledTimes(1))
        const config = adapter.mock.calls[0][0]
        loginAs('bob')
        response.reject(new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, undefined, {
            config, data: {}, status: 401, statusText: 'Unauthorized', headers: {},
        }))
        await expect(saving).rejects.toThrow('登录账号已变化')
        expect(fetch).not.toHaveBeenCalled()
        expect(adapter).toHaveBeenCalledTimes(1)
        expect(authState.username).toBe('bob')
        expect(authState.showLogin).toBe(false)
    })

    it.each([200, 401])('切换账号后到达的刷新响应（%s）不更改新登录态', async (status) => {
        const response = deferred<Response>()
        vi.mocked(fetch).mockReturnValueOnce(response.promise)
        const refreshing = tryRefreshToken()
        loginAs('bob')
        response.resolve(new Response(JSON.stringify({
            username: 'alice', accessToken: 'new-alice-access', refreshToken: 'new-alice-refresh',
        }), { status }))
        expect(await refreshing).toBe(false)
        expect(authState.username).toBe('bob')
        expect(authState.accessToken).toBe('bob-access')
        expect(authState.refreshToken).toBe('bob-refresh')
        expect(authState.showLogin).toBe(false)
    })

    it('读取刷新响应正文期间切换账号，也不覆盖新 token', async () => {
        const body = deferred<unknown>()
        const response = new Response('{}')
        vi.spyOn(response, 'json').mockReturnValueOnce(body.promise)
        vi.mocked(fetch).mockResolvedValueOnce(response)
        const refreshing = tryRefreshToken()
        await Promise.resolve()
        loginAs('bob')
        body.resolve({ username: 'alice', accessToken: 'new-alice-access', refreshToken: 'new-alice-refresh' })
        expect(await refreshing).toBe(false)
        expect(authState.accessToken).toBe('bob-access')
    })
})
