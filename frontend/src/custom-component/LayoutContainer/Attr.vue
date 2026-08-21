<template>
    <div class="attr-list">
        <CommonAttr />
        <el-form>
            <el-form-item label="顶部区域高度">
                <el-input-number v-model="curComponent.propValue.headerHeight" :min="20" :max="300" />
            </el-form-item>
            <el-form-item label="底部区域高度">
                <el-input-number v-model="curComponent.propValue.footerHeight" :min="20" :max="300" />
            </el-form-item>
        </el-form>
    </div>
</template>

<script setup>
import { useStore } from '@/store'
import { storeToRefs } from 'pinia'
import CommonAttr from '@/custom-component/common/CommonAttr.vue'

const store = useStore()
const { curComponent } = storeToRefs(store)
</script>
