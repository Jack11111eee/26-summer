import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  // 公开页
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/register', name: 'Register', component: () => import('../views/Register.vue'), meta: { public: true } },
  // 管理端（素色工作台，需 admin）——统一挂 AdminShell 壳（雾团/侧栏/待办轮询）
  {
    path: '/admin',
    component: () => import('../components/AdminShell.vue'),
    meta: { role: 'admin' },
    children: [
      // meta.keepAlive：进入页面缓存白名单（§5 前端列表页状态缓存，2026-09-08）——
      // 组件名必须 = 路由名（壳内 keep-alive include 以此匹配，页面用 defineOptions 显式命名）
      { path: 'positions', name: 'AdminPositions', component: () => import('../views/admin/Positions.vue'), meta: { keepAlive: true } },
      // 模型聚合（SSOT §8.6，2026-09-08）：跨岗位聚合任务与模型总览，替换原侧栏「岗位详情」死链项
      { path: 'models', name: 'AdminModelAggregation', component: () => import('../views/admin/ModelAggregation.vue'), meta: { keepAlive: true } },
      { path: 'positions/:id', name: 'AdminPositionDetail', component: () => import('../views/admin/PositionDetail.vue') },
      { path: 'positions/:id/review', name: 'AdminModelReview', component: () => import('../views/admin/ModelReview.vue') },
      { path: 'positions/:id/versions', name: 'VersionHistory', component: () => import('../views/admin/VersionHistory.vue') },
      { path: 'qbank', name: 'AdminQbankStatus', component: () => import('../views/admin/QbankStatus.vue'), meta: { keepAlive: true } },
      { path: 'dict', name: 'AdminDict', component: () => import('../views/admin/Dict.vue'), meta: { keepAlive: true } },
      { path: 'users', name: 'AdminUsers', component: () => import('../views/admin/Users.vue'), meta: { keepAlive: true } },
      { path: 'test-center', name: 'AdminTestCenter', component: () => import('../views/admin/TestCenter.vue'), meta: { keepAlive: true } }
    ]
  },
  // 测评端（暖纸对话，登录即可）——四页挂 CandidateShell 壳（§12.6 导航壳）；
  // session（Chat 全屏专注态）/ report（打印 PDF 布局）不挂壳（顶层路由），
  // 全部路径不变（纯 children 化，零破坏）
  {
    path: '/assessment',
    component: () => import('../components/CandidateShell.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: 'positions', name: 'AssessmentPositions', component: () => import('../views/assessment/Positions.vue'), meta: { requiresAuth: true, keepAlive: true } },
      { path: 'positions/:id', name: 'PositionAssess', component: () => import('../views/assessment/PositionAssess.vue'), meta: { requiresAuth: true } },
      { path: 'history', name: 'AssessmentHistory', component: () => import('../views/assessment/History.vue'), meta: { requiresAuth: true, keepAlive: true } },
      { path: 'feedback', name: 'AssessmentFeedback', component: () => import('../views/assessment/Feedback.vue'), meta: { requiresAuth: true, keepAlive: true } }
    ]
  },
  { path: '/assessment/session/:session_id', name: 'AssessmentChat', component: () => import('../views/assessment/Chat.vue'), meta: { requiresAuth: true } },
  { path: '/assessment/report/:session_id', name: 'AssessmentReport', component: () => import('../views/assessment/Report.vue'), meta: { requiresAuth: true } },
  // 根路径与兜底：交给守卫按登录态/角色分发
  { path: '/', redirect: '/login' },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  // 滚动行为（§5 前端列表页状态缓存）：物理前进/后退优先 savedPosition；「返回」均为
  // push 正向导航（savedPosition 恒 undefined），keepAlive 页恢复离开时记录的滚动、
  // 其余新页面一律回顶（修正从长列表进详情停在半空的问题）
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.meta.keepAlive && scrollMemory.has(to.name)) return { top: scrollMemory.get(to.name) }
    return { top: 0 }
  }
})

// keepAlive 页滚动记录：离开（该页 → 任意路由）时记下 scrollY，返回时由 scrollBehavior 恢复
const scrollMemory = new Map()

router.beforeEach((to, from) => {
  if (from.meta.keepAlive) scrollMemory.set(from.name, window.scrollY)

  const auth = useAuthStore()

  if (to.meta.public) {
    // 已登录用户访问登录/注册页时，直接送回角色首页
    if (auth.isLoggedIn) return auth.homePath
    return true
  }

  if (!auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (to.meta.role && auth.user?.role !== to.meta.role) {
    return auth.homePath
  }

  return true
})

export default router
