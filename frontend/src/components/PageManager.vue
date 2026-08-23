<template>
    <Modal v-model="visible">
        <div class="page-manager">
            <div class="header">
                <h3>页面管理</h3>
                <el-button
                    type="primary"
                    size="small"
                    :loading="isSaving"
                    @click="handleCreate"
                >
                    新建页面
                </el-button>
            </div>

            <div v-loading="isLoading" class="page-list">
                <div
                    v-for="page in pages"
                    :key="page._id"
                    class="page-item"
                    :class="{ active: page._id === currentPageId }"
                >
                    <div class="page-info" @click="handleOpen(page._id)">
                        <span class="page-title">{{ page.title || '未命名页面' }}</span>
                        <span class="page-date">{{ formatDate(page.updatedAt) }}</span>
                    </div>
                    <div class="page-actions">
                        <el-icon
                            v-if="page.isPublic"
                            class="action-icon"
                            title="已分享"
                            @click="handleCopyShareLink(page._id)"
                        >
                            <Link />
                        </el-icon>
                        <el-icon class="action-icon" title="分享" @click="handleShare(page._id)">
                            <Share />
                        </el-icon>
                        <el-icon class="action-icon danger" title="删除" @click="handleDelete(page._id)">
                            <Delete />
                        </el-icon>
                    </div>
                </div>
                <div v-if="!isLoading && pages.length === 0" class="empty">
                    暂无页面，点击"新建页面"开始
                </div>
            </div>
        </div>
    </Modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { Link, Share, Delete } from '@element-plus/icons-vue'
import Modal from './Modal.vue'
import { usePageManager } from '@/composables/usePageManager'
import { useStore } from '@/store'
import { storeToRefs } from 'pinia'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<(e: 'update:modelValue', value: boolean) => void>()

const visible = ref(props.modelValue)
watch(() => props.modelValue, v => { visible.value = v })
watch(visible, v => emit('update:modelValue', v))

const store = useStore()
const { currentPageId } = storeToRefs(store)
const { pages, isLoading, isSaving, loadPages, createPage, openPage, deletePage, sharePage } = usePageManager()

watch(visible, v => {
    if (v) loadPages()
})

function formatDate(iso: string): string {
    if (!iso) return ''
    try {
        return new Date(iso).toLocaleString()
    } catch {
        return iso
    }
}

async function handleCreate(): Promise<void> {
    const { value: title } = await ElMessageBox.prompt('请输入页面标题', '新建页面', {
        confirmButtonText: '创建',
        cancelButtonText: '取消',
        inputValue: '未命名页面',
    }).catch(() => ({ value: null }))
    if (title === null) return
    await createPage(title)
    visible.value = false
}

async function handleOpen(id: string): Promise<void> {
    await openPage(id)
    visible.value = false
}

async function handleDelete(id: string): Promise<void> {
    try {
        await ElMessageBox.confirm('确定要删除该页面吗？', '删除页面', {
            confirmButtonText: '删除',
            cancelButtonText: '取消',
            type: 'warning',
        })
    } catch {
        return // 用户取消
    }
    await deletePage(id)
}

async function handleShare(id: string): Promise<void> {
    const url = await sharePage(id)
    if (url) {
        const fullUrl = `${window.location.origin}${url}`
        await navigator.clipboard.writeText(fullUrl)
        ElMessage.success('分享链接已复制到剪贴板')
    }
}

async function handleCopyShareLink(id: string): Promise<void> {
    const page = pages.value.find(p => p._id === id)
    if (!page) return
    // 已分享的页面，直接复制链接
    ElMessage.info('该页面已分享，请通过已生成的链接访问')
}
</script>

<style lang="scss" scoped>
.page-manager {
    display: flex;
    flex-direction: column;
    height: 100%;
    padding: 16px;

    .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 16px;

        h3 {
            margin: 0;
            font-size: 18px;
        }
    }

    .page-list {
        flex: 1;
        overflow-y: auto;
        min-height: 200px;
    }

    .page-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 12px;
        border-radius: 6px;
        cursor: pointer;
        transition: background 0.15s;

        &:hover {
            background: var(--active-bg, #f0f0f0);
        }

        &.active {
            background: var(--primary-bg, #e6f7ff);
        }
    }

    .page-info {
        display: flex;
        flex-direction: column;
        flex: 1;
        min-width: 0;

        .page-title {
            font-weight: 500;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .page-date {
            font-size: 12px;
            color: #999;
            margin-top: 2px;
        }
    }

    .page-actions {
        display: flex;
        gap: 8px;
        margin-left: 12px;
    }

    .action-icon {
        cursor: pointer;
        font-size: 16px;
        color: #666;

        &:hover {
            color: #409eff;
        }

        &.danger:hover {
            color: #f56c6c;
        }
    }

    .empty {
        text-align: center;
        color: #999;
        padding: 40px 0;
    }
}
</style>
