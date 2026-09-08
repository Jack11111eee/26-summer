<template>
  <!-- App 层缓存（§5，2026-09-08）：仅 CandidateShell——候选端 Chat/Report 为顶层路由，
       导航即换壳，不缓存壳则测评历史页缓存随之丢失；:key = 登录身份（JWT sub），
       登出换号销毁壳及全部内层缓存防跨账号残留。AdminShell 不缓存（管理端列表页
       缓存全在壳内层，换账号由 401 拦截器强制整页重载兜底） -->
  <router-view v-slot="{ Component }">
    <keep-alive :include="['CandidateShell']">
      <component :is="Component" :key="auth.userId || 'anon'" />
    </keep-alive>
  </router-view>
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
import { useAuthStore } from './stores/auth'

const route = useRoute()
const auth = useAuthStore()
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
