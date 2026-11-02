import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CanvasStyleSchema } from '@/schemas'
import {
    getDraftKey, readPageDraft, readActiveDraft, writePageDraft, removePageDraft,
    acknowledgeDraft, migrateLegacyDraft, type PageDraft,
} from '@/utils/pageDrafts'

function draft(overrides: Partial<PageDraft> = {}): PageDraft {
    return {
        schemaVersion: 1, owner: 'user:alice', pageId: 'A', draftId: 'local-A', title: 'A',
        componentData: [], canvasStyle: CanvasStyleSchema.parse({}), dirty: true, savedAt: 1,
        ...overrides,
    }
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('隔离的页面草稿', () => {
    it('不同用户、页面与未保存草稿使用不同存储键', () => {
        const one = draft()
        const two = draft({ owner: 'user:bob', title: 'Bob' })
        const three = draft({ pageId: null, draftId: 'one' })
        const four = draft({ pageId: null, draftId: 'two' })
        for (const value of [one, two, three, four]) expect(writePageDraft(value)).toBe(true)
        expect(readPageDraft('user:alice', 'A', '')?.title).toBe('A')
        expect(readPageDraft('user:bob', 'A', '')?.title).toBe('Bob')
        expect(readPageDraft('anonymous', 'A', '')).toBeNull()
        expect(readPageDraft('user:alice', null, 'one')?.draftId).toBe('one')
        expect(readActiveDraft('user:alice')?.draftId).toBe('two')
    })

    it('空画布可以完整恢复，清空操作不会被忽略', () => {
        const value = draft({ canvasStyle: CanvasStyleSchema.parse({ width: 640 }) })
        writePageDraft(value)
        expect(readActiveDraft(value.owner)).toEqual(value)
    })

    it('忽略损坏数据、未知版本和跨用户活动指针', () => {
        const value = draft()
        const key = getDraftKey(value.owner, value.pageId, value.draftId)
        writePageDraft(value)
        localStorage.setItem('lowcode:active-draft:v1:user%3Abob', key)
        expect(readActiveDraft('user:bob')).toBeNull()
        localStorage.setItem(key, '{broken')
        expect(readActiveDraft(value.owner)).toBeNull()
        localStorage.setItem(key, JSON.stringify({ ...value, schemaVersion: 2 }))
        expect(readActiveDraft(value.owner)).toBeNull()
    })

    it('保留 Schema 未声明的组件扩展样式', () => {
        const value = draft()
        const extendedStyle = { width: 100, height: 50, display: 'flex' }
        value.componentData = [{
            id: 'text', component: 'VText', label: 'text', icon: '', propValue: 'hello',
            style: extendedStyle, parentId: null, slot: 'default', zIndex: 1,
            animations: [], events: {}, groupStyle: {}, isLock: false, collapseName: 'style',
            linkage: { duration: 0, data: [] },
        }]
        writePageDraft(value)
        expect(readActiveDraft(value.owner)?.componentData[0].style).toMatchObject({ display: 'flex' })
    })

    it('旧请求的确认不会清除更新草稿的脏标记', () => {
        const sent = draft()
        writePageDraft(draft({ title: 'new title' }))
        acknowledgeDraft(sent, 'A')
        expect(readActiveDraft(sent.owner)?.dirty).toBe(true)
        expect(readActiveDraft(sent.owner)?.title).toBe('new title')
    })

    it('新建响应迁移草稿标识，但不改变另一个页面的活动指针', () => {
        const local = draft({ pageId: null })
        writePageDraft(local)
        writePageDraft(draft({ pageId: 'B', title: 'B' }))
        acknowledgeDraft(local, 'created')
        expect(readPageDraft(local.owner, null, local.draftId)).toBeNull()
        expect(readPageDraft(local.owner, 'created', '')?.dirty).toBe(false)
        expect(readActiveDraft(local.owner)?.pageId).toBe('B')
    })

    it('旧本地身份的确认不会覆盖已迁移的更新草稿', () => {
        const local = draft({ pageId: null })
        writePageDraft(draft({ pageId: 'created', title: 'newer draft' }))
        acknowledgeDraft(local, 'created')
        expect(readActiveDraft(local.owner)?.title).toBe('newer draft')
        expect(readActiveDraft(local.owner)?.dirty).toBe(true)
    })

    it('删除非活动草稿不会清除其他页面的活动指针', () => {
        writePageDraft(draft())
        writePageDraft(draft({ pageId: 'B' }))
        removePageDraft('user:alice', 'A', '')
        expect(readActiveDraft('user:alice')?.pageId).toBe('B')
    })

    it('配额不足时返回失败，不破坏已有草稿', () => {
        writePageDraft(draft())
        vi.spyOn(console, 'warn').mockImplementation(() => {})
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
        expect(writePageDraft(draft({ title: 'new' }))).toBe(false)
        expect(readActiveDraft('user:alice')?.title).toBe('A')
    })

    it('迁移旧版空画布和配置到匿名草稿', () => {
        localStorage.setItem('canvasData', '[]')
        localStorage.setItem('canvasStyle', JSON.stringify({ width: 720 }))
        const migrated = migrateLegacyDraft('legacy')
        expect(migrated?.owner).toBe('anonymous')
        expect(migrated?.canvasStyle.width).toBe(720)
        expect(readActiveDraft('anonymous')?.componentData).toEqual([])
        expect(localStorage.getItem('canvasData')).toBeNull()
    })

    it('迁移写入失败时保留原始数据', () => {
        localStorage.setItem('canvasData', '[]')
        vi.spyOn(console, 'warn').mockImplementation(() => {})
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
        migrateLegacyDraft('legacy')
        expect(localStorage.getItem('canvasData')).toBe('[]')
    })
})
