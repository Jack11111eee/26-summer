import axios from 'axios'
import { ElMessage } from 'element-plus'

// 统一 axios 实例：baseURL 走 Vite 代理到后端
const api = axios.create({
  baseURL: '/api',
  timeout: 15000
})

// 请求拦截器：注入 Bearer token（从 localStorage 读取，避免 Pinia 初始化顺序问题）
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：401 视为会话失效，清理本地状态并跳转登录页
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      // 避免在登录页自身的 401（凭据错误）时重复跳转
      if (window.location.pathname !== '/login') {
        ElMessage.error('登录状态已失效，请重新登录')
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

export default api
