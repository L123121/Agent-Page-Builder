<template>
    <div class="attr-container">
        <p class="title">
            画布属性
        </p>
        <el-form style="padding: 20px;">
            <el-form-item
                v-for="(key, index) in Object.keys(options) as (keyof CanvasStyleData)[]"
                :key="index"
                :label="options[key]"
            >
                <el-color-picker
                    v-if="isIncludesColor(key)"
                    v-model="canvasStyleData[key as keyof CanvasStyleData]"
                    show-alpha
                />
                <el-input
                    v-else
                    v-model.number="canvasStyleData[key as keyof CanvasStyleData]"
                    type="number"
                />
            </el-form-item>
        </el-form>
    </div>
</template>

<script setup lang="ts">
import { useStore } from '@/store'
import { storeToRefs } from 'pinia'
import type { CanvasStyleData } from '@/types'

const store = useStore()
const { canvasStyleData } = storeToRefs(store)

const options: Partial<Record<keyof CanvasStyleData, string>> = {
    color: '颜色',
    opacity: '不透明度',
    backgroundColor: '背景色',
    fontSize: '字体大小',
}

function isIncludesColor(str: string): boolean {
    return str.toLowerCase().includes('color')
}

</script>

<style lang="scss" scoped>
.attr-container {
    padding-top: 10px;
    
    .title {
        text-align: center;
        margin-bottom: 10px;
        height: 40px;
        line-height: 40px;
        border-bottom: 1px solid var(--border-color);
        font-size: 14px;
        font-weight: 500;
        color: var(--text-color);
    }
}
</style>
