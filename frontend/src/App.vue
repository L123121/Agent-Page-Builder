<template>
    <!-- ElementPlus 全局配置：size 保持原项目的 'small' -->
    <el-config-provider size="small">
        <router-view />
        <!-- 全局登录对话框：401 拦截 / 页面管理登出入口触发 -->
        <LoginDialog />
    </el-config-provider>
</template>

<script setup lang="ts">
import LoginDialog from '@/components/Auth/LoginDialog.vue'
</script>

<style>
#app {
  font-family:
    'Helvetica Neue',
    Helvetica,
    Arial,
    'PingFang SC',
    'Hiragino Sans GB',
    'Heiti SC',
    'Microsoft YaHei',
    'WenQuanYi Micro Hei',
    sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-align: center;
  color: #2c3e50;
}
</style>
