<template>
  <div class="admin-root">
    <!-- 动态浅色背景（单团雾，位置由下方 JS 驱动） -->
    <div class="bg"><i ref="blob" class="blob b1"></i></div>

    <!-- 左侧悬停触发区：鼠标贴左缘 → 侧栏伸出；离开 → 收回 -->
    <div class="edge" title="将鼠标移到此处"></div>

    <!-- 侧栏：默认隐藏 -->
    <aside class="sidebar">
      <div class="side-head">
        <span class="side-chip">胜任力系统</span>
        <div class="side-kicker">Admin Console</div>
        <div class="side-name">岗位<em>管理</em></div>
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
          <span
            v-if="item.cntKey && counts[item.cntKey] != null"
            class="cnt"
            :class="{ hot: counts[item.cntKey] > 0 && item.cntHot }"
          >{{ counts[item.cntKey] }}</span>
        </a>
      </nav>

      <div class="side-foot">
        <div class="avatar">{{ initial }}</div>
        <div>
          <div class="side-user">{{ auth.user?.username || 'admin' }}</div>
          <div class="side-role">管理员 · 在线</div>
        </div>
        <button class="row-btn side-theme" :title="isDark ? '切换到日间' : '切换到夜间'" @click="toggleTheme">{{ isDark ? '日间' : '夜间' }}</button>
        <button class="row-btn" style="margin-left: auto" @click="onLogout">退出</button>
      </div>
    </aside>

    <!-- 主区：列表页 keep-alive 白名单（§5，2026-09-08）——include 由路由 meta.keepAlive 派生，组件名 = 路由名 -->
    <main class="main">
      <router-view v-slot="{ Component }">
        <keep-alive :include="keepAliveNames">
          <component :is="Component" />
        </keep-alive>
      </router-view>
    </main>
  </div>
</template>

<script setup>
// 管理端壳：定稿 admin.html 的 bg 雾团 + edge + 弹出侧栏原样移植为 Vue。
// 子页面（router-view）渲染在各管理路由下，路由由本壳的 <main> 承载。
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../api'
import { useAuthStore } from '../stores/auth'
import { useTheme } from '../lib/theme'
import { toast } from './ui'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

// 全站日/夜切换（SSOT §5 2026-09-09）：侧栏 side-foot 常驻按钮（admin 暗色板见 admin.css）
const { theme, toggle: toggleTheme } = useTheme()
const isDark = computed(() => theme.value === 'dark')

const navItems = [
  { path: '/admin/positions', label: '岗位库', cntKey: 'pending_positions', cntHot: true },
  // 模型聚合（SSOT §8.6，2026-09-08）：替换原「岗位详情」死链项（/admin/positions/detail
  // 会被 positions/:id 路由吞作岗位 ID）；stalled 徽标数据源 todos.stalled_models 既有轮询
  { path: '/admin/models', label: '模型聚合', cntKey: 'stalled_models', cntHot: true },
  { path: '/admin/qbank', label: '题库状态', cntKey: 'question_bank_not_ready', cntHot: true },
  { path: '/admin/dict', label: '能力词典', cntKey: 'dict_llm_pending', cntHot: true },
  { path: '/admin/users', label: '用户管理', cntKey: 'user_total' },
  { path: '/admin/test-center', label: '测试中心', cntKey: 'feedback_pending', cntHot: true }
]

// 待办计数（todos 轮询 + 词典/用户轻量计数，30s 节流；详情页等二级路由沿父项高亮）
const counts = reactive({
  pending_positions: null,
  question_bank_not_ready: null,
  stalled_models: null,
  orphan_jds: null,
  dict_llm_pending: null,
  user_total: null,
  feedback_pending: null
})

const initial = computed(() => (auth.user?.username || 'A').slice(0, 1).toUpperCase())

// keep-alive include：/admin 前缀下 meta.keepAlive 路由的组件名（单一来源在路由表）。
// router = useRouter() 返回的实例，getRoutes() 为路由表静态派生、运行期不变，非响应式
const keepAliveNames = router
  .getRoutes()
  .filter((r) => r.meta.keepAlive && r.path.startsWith('/admin'))
  .map((r) => r.name)

function isActive(item) {
  if (item.path === '/admin/positions') {
    return route.path === '/admin/positions' || /^\/admin\/positions\/.+/.test(route.path)
  }
  return route.path.startsWith(item.path)
}

function go(e, item) {
  // 鼠标点击（e.detail>0）导航后立即失焦，让侧栏回到「鼠标离开即收回」；
  // 键盘 Enter（detail=0）保留焦点，focus-within 可达性不受影响。
  if (e && e.detail > 0) e.currentTarget.blur()
  if (route.path !== item.path) router.push(item.path)
}

function onLogout() {
  auth.logout()
  router.push('/login')
}

// ---- todos 轮询（30s）----
let todosTimer = null
async function pollCounts() {
  try {
    const { data } = await api.get('/admin/todos')
    counts.pending_positions = data.pending_positions
    counts.question_bank_not_ready = data.question_bank_not_ready
    counts.stalled_models = data.stalled_models
    counts.orphan_jds = data.orphan_jds
  } catch { /* 轮询失败静默，下轮再试 */ }
  try {
    const { data } = await api.get('/admin/dict', { params: { page: 1, page_size: 1, created_by: 'llm_pending' } })
    counts.dict_llm_pending = data.total
  } catch { /* ignore */ }
  try {
    const { data } = await api.get('/admin/users', { params: { page: 1, page_size: 1 } })
    counts.user_total = data.total
  } catch { /* ignore */ }
  try {
    const { data } = await api.get('/admin/feedback/list', { params: { status: 'pending' } })
    counts.feedback_pending = Array.isArray(data) ? data.length : 0
  } catch { /* ignore */ }
}

// ---- 雾团轨迹（admin.html 原样移植：80% Lissajous + 15% 低频噪声 + 5% 平滑微扰）----
const blob = ref(null)
let rafId = 0
let cfg = null
let onResize = null

function startBlob() {
  if (!blob.value) return
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return // 动效敏感用户：静态雾
  const vw = window.innerWidth
  const vh = window.innerHeight
  const r = (a, b) => a + Math.random() * (b - a)
  cfg = {
    cx: vw * .5, cy: vh * .5, ax: vw * .30, ay: vh * .18,
    kx: [1.00, 2.07, 2.91], ky: [1.00, 1.63, 2.47],   /* 略偏离整数倍 → 不对称 */
    wx: [0.68, 0.20, 0.12], wy: [0.66, 0.22, 0.12],
    px: [r(0, 6.28), r(0, 6.28), r(0, 6.28)],
    py: [r(0, 6.28), r(0, 6.28), r(0, 6.28)],
    nf: [1 / 1.9, 1 / 3.1],                            /* 噪声：周期 ~104s / ~170s */
    np: [r(0, 6.28), r(0, 6.28), r(0, 6.28), r(0, 6.28)],
    jx: 0, jy: 0, jtx: r(-1, 1), jty: r(-1, 1), jtt: 0, jtk: r(0, 1.4)
  }
  onResize = () => {
    cfg.cx = window.innerWidth * .5
    cfg.cy = window.innerHeight * .5
    cfg.ax = window.innerWidth * .30
    cfg.ay = window.innerHeight * .18
  }
  window.addEventListener('resize', onResize)

  const HALF = 420 /* 840px 雾团半径的一半，使 translate 对准元素中心 */
  const T = 55
  let t0 = null
  let last = 0
  const frame = (ts) => {
    if (t0 === null) { t0 = ts; last = ts }
    const dt = Math.min((ts - last) / 1000, 0.1)
    last = ts
    const t = (ts - t0) / 1000
    const th = 2 * Math.PI * t / T
    const c = cfg
    /* 微小随机扰动：慢速重定向 + 指数平滑（≈5%） */
    c.jtt += dt
    if (c.jtt > c.jtk) {
      c.jtx = Math.random() * 2 - 1
      c.jty = Math.random() * 2 - 1
      c.jtt = 0
      c.jtk = 0.8 + Math.random() * 1.2
    }
    const sm = 1 - Math.exp(-dt * 1.6)
    c.jx += (c.jtx - c.jx) * sm
    c.jy += (c.jty - c.jy) * sm
    /* 确定性主轨迹（≈80%） */
    let mx = 0, my = 0
    for (let k = 0; k < 3; k++) {
      mx += c.wx[k] * Math.sin(c.kx[k] * th + c.px[k])
      my += c.wy[k] * Math.sin(c.ky[k] * th + c.py[k])
    }
    /* 低频噪声（≈15%） */
    const no = 0.6 * Math.sin(2 * Math.PI * t * c.nf[0] / T + c.np[0]) + 0.4 * Math.sin(2 * Math.PI * t * c.nf[1] / T + c.np[1])
    const noy = 0.6 * Math.sin(2 * Math.PI * t * c.nf[1] / T + c.np[2]) + 0.4 * Math.sin(2 * Math.PI * t * c.nf[0] / T + c.np[3])
    const x = c.cx + c.ax * (mx + 0.15 * no + 0.05 * c.jx)
    const y = c.cy + c.ay * (my + 0.15 * noy + 0.05 * c.jy)
    blob.value.style.transform = `translate(${(x - HALF).toFixed(1)}px,${(y - HALF).toFixed(1)}px)`
    rafId = requestAnimationFrame(frame)
  }
  rafId = requestAnimationFrame(frame)
}

onMounted(() => {
  pollCounts()
  todosTimer = setInterval(pollCounts, 30000)
  startBlob()
})

onBeforeUnmount(() => {
  if (todosTimer) clearInterval(todosTimer)
  if (rafId) cancelAnimationFrame(rafId)
  if (onResize) window.removeEventListener('resize', onResize)
})
</script>
