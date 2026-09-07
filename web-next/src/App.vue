<template>
  <router-view />
  <UiToast />
</template>

<script setup>
// 根组件：路由出口 + 全局 toast。
// body class 按顶层路由段挂 admin / candidate（两套 CSS 体系的作用域），
// 在导航后置钩子里同步，页面自身无需操心。
import { watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import UiToast from './components/ui/UiToast.vue'
import { useTheme } from './lib/theme'

const route = useRoute()
useTheme() // 暖纸双主题初始化（data-theme 挂 html；admin 页不消费也无副作用）

watchEffect(() => {
  const seg = route.path.split('/')[1]
  if (seg === 'admin') {
    document.body.className = 'admin'
  } else {
    // login / register / assessment 全部走暖纸体系
    document.body.className = 'candidate'
  }
})
</script>
