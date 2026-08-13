import { defineStore } from 'pinia'
import type {
    StoreState,
    ComponentData,
    CanvasStyleData,
    AreaData,
    SetCurComponentPayload,
    SetShapeStylePayload,
    AddComponentPayload,
    AddEventPayload,
    AlterAnimationPayload,
    ShowContextMenuPayload,
} from '@/types'
import { deepCopy, $ } from '@/utils/utils'
import type { AnimationItem } from '@/utils/animationClassData'
import { ElMessage } from 'element-plus'
import generateID from '@/utils/generateID'
import { setCommandContext } from '@/commands/BaseCommand'
import { createCommandContext } from '@/commands/localContext'
import { moveArrayItem, normalizeComponentLayerOrder, normalizeComponentZIndex, resolveLayerInsertIndex } from '@/utils/layer'

export const useStore = defineStore('main', {
    state: (): StoreState => ({
        editMode: 'edit',
        canvasStyleData: {
            width: 1200,
            height: 740,
            scale: 100,
            color: '#000',
            opacity: 1,
            backgroundColor: '#fff',
            fontSize: 14,
        },
        componentData: [],
        // parentId → 子组件数组 的索引，O(1) 查询子组件（替代 O(n) filter）
        childrenIndex: new Map<string, ComponentData[]>(),
        curComponent: null,
        curComponentIndex: null,
        isClickComponent: false,
        editor: null,
        menuTop: 0,
        menuLeft: 0,
        menuShow: false,
        copyData: null,
        isDarkMode: false,
        rightList: true,
        isInEditor: false,
        areaData: {
            style: {
                top: 0,
                left: 0,
                width: 0,
                height: 0,
            },
            components: [],
        },
        versions: [],
        dataVersion: 0,
        // 后端持久化状态
        currentPageId: null,
        currentPageTitle: '未命名页面',
        isSaving: false,
        lastSyncedVersion: 0,
    }),

    actions: {
        /** 标记数据已变更，触发自动保存 */
        markDataDirty(): void {
            this.dataVersion++
        },

        /**
         * 注入命令上下文(初始化时调用)。
         */
        initCommandContext(): void {
            setCommandContext(createCommandContext())
        },

        setClickComponentStatus(status: boolean): void {
            this.isClickComponent = status
        },

        setEditor(el: HTMLElement): void {
            this.editor = el
        },

        getEditor(): void {
            this.editor = $('#editor')
        },

        setAreaData(data: AreaData): void {
            this.areaData = data
        },

        // ==================== 后端持久化 ====================

        /** 设置当前页面 ID（打开已有页面或保存新页面后调用） */
        setCurrentPage(id: string, title?: string): void {
            this.currentPageId = id
            if (title !== undefined) this.currentPageTitle = title
            this.lastSyncedVersion = this.dataVersion
        },

        /** 标记已与后端同步 */
        markSynced(): void {
            this.lastSyncedVersion = this.dataVersion
        },

        /** 当前数据是否与后端有未同步的变更 */
        isDirty(): boolean {
            return this.dataVersion !== this.lastSyncedVersion
        },

        setCanvasStyle(style: CanvasStyleData): void {
            this.canvasStyleData = style
        },

        setCurComponent({ component, index }: SetCurComponentPayload): void {
            this.curComponent = component
            this.curComponentIndex = index
        },

        setShapeStyle({ top, left, width, height, rotate }: SetShapeStylePayload): void {
            if (!this.curComponent) return

            if (top !== undefined) { this.curComponent.style.top = Math.round(top) }
            if (left !== undefined) { this.curComponent.style.left = Math.round(left) }
            if (width !== undefined) { this.curComponent.style.width = Math.round(width) }
            if (height !== undefined) { this.curComponent.style.height = Math.round(height) }
            if (rotate !== undefined) { this.curComponent.style.rotate = Math.round(rotate) }
        },

        setShapeSingleStyle({ key, value }: { key: string; value: unknown }): void {
            if (this.curComponent) {
                (this.curComponent.style as Record<string, unknown>)[key] = value
            }
        },

        setComponentData(componentData: ComponentData[] = []): void {
            this.componentData = componentData
            // 统一图层策略：数组顺序为准，zIndex 按数组顺序连续镜像
            this.ensureZIndex()
            this.markDataDirty()
            this.rebuildChildrenIndex()
        },

        /**
         * 重建 parentId → children[] 索引。
         * 在 setComponentData（全量设置）后调用，保证索引与 componentData 一致。
         */
        rebuildChildrenIndex(): void {
            const index = new Map<string, ComponentData[]>()
            for (const c of this.componentData) {
                if (c.parentId) {
                    const list = index.get(c.parentId)
                    if (list) {
                        list.push(c)
                    } else {
                        index.set(c.parentId, [c])
                    }
                }
            }
            this.childrenIndex = index
        },

        /**
         * 增量插入组件到 childrenIndex。
         */
        indexAddComponent(component: ComponentData): void {
            if (!component.parentId) return
            const list = this.childrenIndex.get(component.parentId)
            if (list) {
                list.push(component)
            } else {
                this.childrenIndex.set(component.parentId, [component])
            }
        },

        /**
         * 增量从 childrenIndex 移除组件。
         */
        indexRemoveComponent(component: ComponentData): void {
            if (!component.parentId) return
            const list = this.childrenIndex.get(component.parentId)
            if (!list) return
            const i = list.findIndex(c => c.id === component.id)
            if (i !== -1) {
                list.splice(i, 1)
                if (list.length === 0) {
                    this.childrenIndex.delete(component.parentId)
                }
            }
        },

        addComponent({ component, index }: AddComponentPayload): void {
            const insertIndex = resolveLayerInsertIndex(this.componentData.length, index)
            this.componentData.splice(insertIndex, 0, component)
            normalizeComponentZIndex(this.componentData)
            this.markDataDirty()
            this.indexAddComponent(component)
        },

        /**
         * 按 zIndex 兼容旧数据后，再按数组顺序分配连续 zIndex（1,2,3...）
         */
        ensureZIndex(): void {
            normalizeComponentLayerOrder(this.componentData)
        },

        deleteComponent(index?: number): void {
            if (index === undefined) {
                index = this.curComponentIndex ?? undefined
            }

            if (index === undefined) return

            if (index === this.curComponentIndex) {
                this.curComponentIndex = null
                this.curComponent = null
            }

            if (typeof index === 'number' && index >= 0) {
                // 先记录被删组件信息，用于增量更新 childrenIndex
                const [removed] = this.componentData.splice(index, 1)
                if (removed) {
                    this.indexRemoveComponent(removed)
                }
                normalizeComponentZIndex(this.componentData)
                this.markDataDirty()
            }
        },

        toggleRightList(): void {
            this.rightList = !this.rightList
        },

        updateComponentProps(data: Partial<ComponentData>): void {
            if (this.curComponent) {
                Object.assign(this.curComponent, data)
            }
        },

        upComponent(): void {
            if (!this.curComponent) { ElMessage.warning('请选择组件'); return }
            const index = this.componentData.findIndex(c => c.id === this.curComponent!.id)
            if (index === -1 || index >= this.componentData.length - 1) { ElMessage.warning('已经到顶了'); return }
            moveArrayItem(this.componentData, index, index + 1)
            normalizeComponentZIndex(this.componentData)
            this.curComponentIndex = index + 1
            this.markDataDirty()
        },

        downComponent(): void {
            if (!this.curComponent) { ElMessage.warning('请选择组件'); return }
            const index = this.componentData.findIndex(c => c.id === this.curComponent!.id)
            if (index <= 0) { ElMessage.warning('已经到底了'); return }
            moveArrayItem(this.componentData, index, index - 1)
            normalizeComponentZIndex(this.componentData)
            this.curComponentIndex = index - 1
            this.markDataDirty()
        },

        topComponent(): void {
            if (!this.curComponent) { ElMessage.warning('请选择组件'); return }
            const index = this.componentData.findIndex(c => c.id === this.curComponent!.id)
            if (index === -1 || index >= this.componentData.length - 1) { ElMessage.warning('已经到顶了'); return }
            moveArrayItem(this.componentData, index, this.componentData.length - 1)
            normalizeComponentZIndex(this.componentData)
            this.curComponentIndex = this.componentData.length - 1
            this.markDataDirty()
        },

        bottomComponent(): void {
            if (!this.curComponent) { ElMessage.warning('请选择组件'); return }
            const index = this.componentData.findIndex(c => c.id === this.curComponent!.id)
            if (index <= 0) { ElMessage.warning('已经到底了'); return }
            moveArrayItem(this.componentData, index, 0)
            normalizeComponentZIndex(this.componentData)
            this.curComponentIndex = 0
            this.markDataDirty()
        },

        addAnimation(animation: AnimationItem | { label: string; value: string }): void {
            if (this.curComponent) {
                this.curComponent.animations.push({
                    label: animation.label,
                    type: animation.value,
                    duration: 1000,
                    delay: 0,
                    iterationNum: 1,
                    infinite: false,
                    applyTo: 'enter',
                })
            }
        },

        removeAnimation(index: number): void {
            if (this.curComponent) {
                this.curComponent.animations.splice(index, 1)
            }
        },

        addEvent({ event, param }: AddEventPayload): void {
            if (this.curComponent) {
                this.curComponent.events[event] = param
            }
        },

        removeEvent(event: string): void {
            if (this.curComponent) {
                delete this.curComponent.events[event]
            }
        },

        alterAnimation({ index, data = {} }: AlterAnimationPayload): void {
            if (this.curComponent && typeof index === 'number') {
                const original = this.curComponent.animations[index]
                if (original) {
                    this.curComponent.animations[index] = { ...original, ...data }
                }
            }
        },

        /**
         * 刷新当前组件引用（撤销重做后需要）
         */
        refreshCurComponent(): void {
            if (this.curComponent) {
                const idx = this.componentData.findIndex(c => c.id === this.curComponent!.id)
                if (idx !== -1) {
                    this.curComponent = this.componentData[idx]
                    this.curComponentIndex = idx
                } else {
                    this.curComponent = null
                    this.curComponentIndex = null
                }
            }
        },

        setEditMode(mode: 'edit' | 'preview'): void {
            this.editMode = mode
        },

        setInEditorStatus(status: boolean): void {
            this.isInEditor = status
        },

        showContextMenu({ top, left }: ShowContextMenuPayload): void {
            this.menuShow = true
            this.menuTop = top
            this.menuLeft = left
        },

        hideContextMenu(): void {
            this.menuShow = false
        },

        toggleDarkMode(val: boolean): void {
            this.isDarkMode = val
            localStorage.setItem('isDarkMode', String(val))
        },

        lock(): void {
            if (this.curComponent) {
                this.curComponent.isLock = true
            }
        },

        unlock(): void {
            if (this.curComponent) {
                this.curComponent.isLock = false
            }
        },

        copy(): void {
            if (!this.curComponent) {
                ElMessage.warning('请选择组件')
                return
            }

            // 如果有剪切数据，需要先还原
            if (this.copyData) {
                this.copyData = null
            }

            this.copyData = {
                data: deepCopy(this.curComponent),
                index: this.curComponentIndex!,
            }
        },

        paste(isMouse?: boolean): void {
            if (!this.copyData) {
                ElMessage.warning('请选择组件')
                return
            }

            const data = deepCopy(this.copyData.data)

            if (isMouse) {
                data.style.top = this.menuTop
                data.style.left = this.menuLeft
            } else {
                data.style.top = (data.style.top ?? 0) + 10
                data.style.left = (data.style.left ?? 0) + 10
            }

            data.id = generateID()

            // Group's sub components id
            if (data.component === 'Group') {
                (data.propValue as ComponentData[]).forEach(component => {
                    component.id = generateID()
                })
            }

            this.addComponent({ component: deepCopy(data) })

            if (this.copyData.isCut) {
                this.copyData = null
            }
        },

    },
})

export function setDefaultcomponentData(data: ComponentData[] = []): void {
    const store = useStore()
    store.setComponentData(data)
}
