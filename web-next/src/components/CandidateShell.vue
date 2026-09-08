<template>
  <div class="candidate-shell-root">
    <!-- 左侧悬停触发区：鼠标贴左缘 → 侧栏伸出；离开 → 收回（镜像 admin 形态，零 JS 状态） -->
    <div class="edge" title="将鼠标移到此处"></div>

    <!-- 侧栏：默认藏屏外 -->
    <aside class="sidebar">
      <div class="side-head">
        <span class="side-chip">胜任力测评</span>
        <div class="side-kicker">Candidate Console</div>
        <div class="side-name">测评<em>中心</em></div>
      </div>

      <nav class="nav">
        <a
          v-for="item in navItems"
          :key="item.path"
          class="nav-item"
          :class="{ active: isActive(item) }"
          :href="item.path"
          @click.prevent="go($event, item)"
        >
          {{ item.label }}
        </a>
      </nav>

      <div class="side-foot">
        <div class="avatar">{{ initial }}</div>
        <div>
          <div class="side-user">{{ auth.user?.username || 'candidate' }}</div>
          <div class="side-role">候选人 · 在线</div>
        </div>
        <button class="row-btn" style="margin-left: auto" @click="onLogout">退出</button>
      </div>
    </aside>

    <!-- 主区：列表页 keep-alive 白名单（§5，2026-09-08）——include 由路由 meta.keepAlive 派生，组件名 = 路由名 -->
    <main class="shell-main">
      <router-view v-slot="{ Component }">
        <keep-alive :include="keepAliveNames">
          <component :is="Component" />
        </keep-alive>
      </router-view>
    </main>
  </div>
</template>

<script setup>
// 候选端导航壳（SSOT §12.6 2026-09-08）：纯 CSS hover drawer 镜像管理端 AdminShell 形态，
// 样式 scoped 到 candidate.css 的 .candidate 前缀（暖纸配色，不污染 admin.css）。
// 登出为纯前端动作（JWT 无状态 12h、无服务端会话——清 localStorage 落 login，by-design）。
defineOptions({ name: 'CandidateShell' }) // App 层 keep-alive include 依名匹配（§5，2026-09-08）
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const navItems = [
  { path: '/assessment/positions', label: '岗位选择' },
  { path: '/assessment/history', label: '测评历史' },
  { path: '/assessment/feedback', label: '意见反馈' }
]

const initial = computed(() => (auth.user?.username || 'C').slice(0, 1).toUpperCase())

// keep-alive include：/assessment 前缀下 meta.keepAlive 路由的组件名（单一来源在路由
// 表；router = useRouter() 实例，getRoutes() 静态派生非响应式）
const keepAliveNames = router
  .getRoutes()
  .filter((r) => r.meta.keepAlive && r.path.startsWith('/assessment'))
  .map((r) => r.name)

function isActive(item) {
  if (item.path === '/assessment/positions') {
    return route.path === '/assessment/positions' || /^\/assessment\/positions\/.+/.test(route.path)
  }
  return route.path.startsWith(item.path)
}

function go(e, item) {
  // 鼠标点击（e.detail>0）导航后立即失焦，让侧栏回到「鼠标离开即收回」；
  // 键盘 Enter（detail=0）保留焦点，focus-within 可达性不受影响（照抄 AdminShell）。
  if (e && e.detail > 0) e.currentTarget.blur()
  if (route.path !== item.path) router.push(item.path)
}

function onLogout() {
  auth.logout()
  router.push('/login')
}
</script>
