import { defineStore } from 'pinia'
import api from '../api'

const TOKEN_KEY = 'token'
const USER_KEY = 'user'

// 认证状态：token 持久化到 localStorage，刷新页面后由 fetchMe 恢复会话
export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  }),
  getters: {
    isLoggedIn: (state) => !!state.token,
    // 按角色返回首页路径
    homePath: (state) =>
      state.user?.role === 'admin' ? '/admin/positions' : '/assessment/positions'
  },
  actions: {
    // 登录：POST /api/auth/login -> {token, user:{username, role}}
    async login(username, password) {
      const { data } = await api.post('/auth/login', { username, password })
      this._persist(data.token, data.user)
      return data.user
    },
    // 注册：POST /api/auth/register -> {user_id, username, role}（后端固定 candidate）
    async register(username, password) {
      const { data } = await api.post('/auth/register', { username, password })
      return data
    },
    // 拉取当前用户信息（用于刷新后恢复/校验会话）
    async fetchMe() {
      const { data } = await api.get('/auth/me')
      this.user = { username: data.username, role: data.role }
      localStorage.setItem(USER_KEY, JSON.stringify(this.user))
      return this.user
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    },
    _persist(token, user) {
      this.token = token
      this.user = user
      localStorage.setItem(TOKEN_KEY, token)
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    }
  }
})
