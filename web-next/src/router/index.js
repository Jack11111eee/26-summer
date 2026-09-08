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
      { path: 'positions', name: 'AdminPositions', component: () => import('../views/admin/Positions.vue') },
      { path: 'positions/:id', name: 'AdminPositionDetail', component: () => import('../views/admin/PositionDetail.vue') },
      { path: 'positions/:id/review', name: 'AdminModelReview', component: () => import('../views/admin/ModelReview.vue') },
      { path: 'positions/:id/versions', name: 'VersionHistory', component: () => import('../views/admin/VersionHistory.vue') },
      { path: 'qbank', name: 'AdminQbankStatus', component: () => import('../views/admin/QbankStatus.vue') },
      { path: 'dict', name: 'AdminDict', component: () => import('../views/admin/Dict.vue') },
      { path: 'users', name: 'AdminUsers', component: () => import('../views/admin/Users.vue') },
      { path: 'test-center', name: 'AdminTestCenter', component: () => import('../views/admin/TestCenter.vue') }
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
      { path: 'positions', name: 'AssessmentPositions', component: () => import('../views/assessment/Positions.vue'), meta: { requiresAuth: true } },
      { path: 'positions/:id', name: 'PositionAssess', component: () => import('../views/assessment/PositionAssess.vue'), meta: { requiresAuth: true } },
      { path: 'history', name: 'AssessmentHistory', component: () => import('../views/assessment/History.vue'), meta: { requiresAuth: true } },
      { path: 'feedback', name: 'AssessmentFeedback', component: () => import('../views/assessment/Feedback.vue'), meta: { requiresAuth: true } }
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
  routes
})

// 全局前置守卫：未登录 -> /login；角色不符 -> 按角色回各自首页
router.beforeEach((to) => {
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
