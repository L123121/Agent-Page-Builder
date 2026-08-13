import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import { fileURLToPath } from 'url'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
    plugins: [
        vue(),
        // ElementPlus 按需引入：自动解析组件与样式，大幅缩减首屏 bundle
        Components({
            resolvers: [ElementPlusResolver()],
        }),
    ],
    resolve: {
        alias: {
            '@': path.resolve(__dirname, './src'),
        },
    },
    server: {
        port: 8080,
    },
    build: {
        chunkSizeWarningLimit: 1000,
        rollupOptions: {
            output: {
                manualChunks: {
                    // Vue 核心
                    'vue-vendor': ['vue', 'vue-router', 'pinia'],
                    // UI 框架
                    'element-plus': ['element-plus', '@element-plus/icons-vue'],
                    // 图表（vue-echarts 自带 echarts 依赖）
                    'echarts-vendor': ['vue-echarts'],
                    // 代码编辑器
                    'editor-vendor': ['ace-builds'],
                },
            },
        },
    },
})