import { z } from 'zod'
import { CanvasStyleSchema, ComponentDataSchema } from '@/schemas'
import type { CanvasStyleData, ComponentData } from '@/types'

export interface PageDraft {
    schemaVersion: 1
    owner: string
    pageId: string | null
    draftId: string
    title: string
    componentData: ComponentData[]
    canvasStyle: CanvasStyleData
    dirty: boolean
    savedAt: number
}

const DraftSchema = z.object({
    schemaVersion: z.literal(1),
    owner: z.string(),
    pageId: z.string().min(1).nullable(),
    draftId: z.string().min(1),
    title: z.string(),
    componentData: z.array(ComponentDataSchema),
    canvasStyle: CanvasStyleSchema,
    dirty: z.boolean(),
    savedAt: z.number().finite(),
})

export function getDraftKey(owner: string, pageId: string | null, draftId: string): string {
    const documentId = pageId ? `page:${pageId}` : `local:${draftId}`
    return `lowcode:draft:v1:${encodeURIComponent(owner)}:${encodeURIComponent(documentId)}`
}

function activeKey(owner: string): string {
    return `lowcode:active-draft:v1:${encodeURIComponent(owner)}`
}

function readDraftAt(key: string, owner: string): PageDraft | null {
    try {
        const value = localStorage.getItem(key)
        if (!value) return null
        const raw: unknown = JSON.parse(value)
        const result = DraftSchema.safeParse(raw)
        if (!result.success || result.data.owner !== owner) return null
        const draft = result.data
        if (getDraftKey(owner, draft.pageId, draft.draftId) !== key) return null
        // 校验后保留组件扩展属性，避免 Schema 裁剪自定义样式和组件配置。
        return {
            ...draft,
            componentData: (raw as PageDraft).componentData,
            canvasStyle: (raw as PageDraft).canvasStyle,
        }
    } catch {
        return null
    }
}

export function readPageDraft(owner: string, pageId: string | null, draftId: string): PageDraft | null {
    return readDraftAt(getDraftKey(owner, pageId, draftId), owner)
}

export function readActiveDraft(owner: string): PageDraft | null {
    try {
        const key = localStorage.getItem(activeKey(owner))
        return key ? readDraftAt(key, owner) : null
    } catch {
        return null
    }
}

export function writePageDraft(draft: PageDraft, makeActive = true): boolean {
    try {
        const key = getDraftKey(draft.owner, draft.pageId, draft.draftId)
        localStorage.setItem(key, JSON.stringify(draft))
        if (makeActive) localStorage.setItem(activeKey(draft.owner), key)
        return true
    } catch (error) {
        console.warn('[page-draft] 本地草稿写入失败:', error)
        return false
    }
}

export function removePageDraft(owner: string, pageId: string | null, draftId: string): void {
    try {
        const key = getDraftKey(owner, pageId, draftId)
        localStorage.removeItem(key)
        if (localStorage.getItem(activeKey(owner)) === key) localStorage.removeItem(activeKey(owner))
    } catch (error) {
        console.warn('[page-draft] 本地草稿清理失败:', error)
    }
}

export function sameDraftContent(left: PageDraft, right: PageDraft): boolean {
    return left.title === right.title
        && JSON.stringify(left.componentData) === JSON.stringify(right.componentData)
        && JSON.stringify(left.canvasStyle) === JSON.stringify(right.canvasStyle)
}

export function acknowledgeDraft(snapshot: PageDraft, pageId: string): void {
    const draft = readPageDraft(snapshot.owner, pageId, snapshot.draftId)
        ?? readPageDraft(snapshot.owner, snapshot.pageId, snapshot.draftId)
        ?? snapshot
    const active = readActiveDraft(snapshot.owner)
    const wasActive = !!active && getDraftKey(active.owner, active.pageId, active.draftId)
        === getDraftKey(snapshot.owner, snapshot.pageId, snapshot.draftId)
    const saved = writePageDraft({ ...draft, pageId, dirty: !sameDraftContent(draft, snapshot) }, wasActive)
    if (saved && !snapshot.pageId) removePageDraft(snapshot.owner, null, snapshot.draftId)
}

export function migrateLegacyDraft(draftId: string): PageDraft | null {
    try {
        const data = localStorage.getItem('canvasData')
        const style = localStorage.getItem('canvasStyle')
        if (!data && !style) return null
        const components = z.array(ComponentDataSchema).safeParse(data ? JSON.parse(data) : [])
        const canvas = CanvasStyleSchema.safeParse(style ? JSON.parse(style) : {})
        if (!components.success || !canvas.success) return null
        const draft: PageDraft = {
            schemaVersion: 1,
            owner: 'anonymous',
            pageId: null,
            draftId,
            title: '未命名页面',
            componentData: components.data,
            canvasStyle: canvas.data,
            dirty: true,
            savedAt: Date.now(),
        }
        if (writePageDraft(draft)) {
            localStorage.removeItem('canvasData')
            localStorage.removeItem('canvasStyle')
        }
        return draft
    } catch {
        return null
    }
}
