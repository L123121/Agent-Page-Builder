<template>
    <el-dialog
        v-model="authState.showLogin"
        :title="mode === 'login' ? '登录' : '注册'"
        width="360px"
        :close-on-click-modal="false"
    >
        <div class="auth-tip">
            登录后可使用页面云同步与 AI 生成；画布编辑本身离线可用
        </div>
        <el-form label-position="top" @submit.prevent>
            <el-form-item label="用户名">
                <el-input
                    v-model="username"
                    placeholder="3-32 位字母/数字/下划线"
                    maxlength="32"
                    @keydown.enter="handleSubmit"
                />
            </el-form-item>
            <el-form-item label="密码">
                <el-input
                    v-model="password"
                    type="password"
                    show-password
                    :placeholder="mode === 'register' ? '至少 8 位' : '请输入密码'"
                    maxlength="64"
                    @keydown.enter="handleSubmit"
                />
            </el-form-item>
        </el-form>
        <template #footer>
            <div class="auth-footer">
                <el-button text size="small" @click="toggleMode">
                    {{ mode === 'login' ? '没有账号？去注册' : '已有账号？去登录' }}
                </el-button>
                <el-button
                    type="primary"
                    :loading="submitting"
                    :disabled="!username.trim() || !password"
                    @click="handleSubmit"
                >
                    {{ mode === 'login' ? '登录' : '注册并登录' }}
                </el-button>
            </div>
        </template>
    </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { authState, authLogin, authRegister } from '@/utils/auth'

const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const submitting = ref(false)

// 打开对话框时重置表单与模式
watch(() => authState.showLogin, (visible) => {
    if (visible) {
        username.value = authState.username || ''
        password.value = ''
        mode.value = 'login'
    }
})

function toggleMode(): void {
    mode.value = mode.value === 'login' ? 'register' : 'login'
}

async function handleSubmit(): Promise<void> {
    const name = username.value.trim()
    if (!name || !password.value || submitting.value) return
    if (mode.value === 'register' && (name.length < 3 || password.value.length < 8)) {
        ElMessage.warning('用户名至少 3 位，密码至少 8 位')
        return
    }
    submitting.value = true
    try {
        const tokens = mode.value === 'login'
            ? await authLogin(name, password.value)
            : await authRegister(name, password.value)
        authState.showLogin = false
        ElMessage.success(`欢迎，${tokens.username}`)
    } catch (e) {
        ElMessage.error(e instanceof Error ? e.message : '认证失败')
    } finally {
        submitting.value = false
    }
}
</script>

<style scoped lang="scss">
.auth-tip {
    font-size: 12px;
    color: #909399;
    margin-bottom: 12px;
}

.auth-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
}
</style>
