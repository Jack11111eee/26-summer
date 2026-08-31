import axios from 'axios'
import { ElMessage } from 'element-plus'
import { streamAnswer } from '../utils/sse'

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

// 测评端（模块二）接口集合。除流式作答外均走上方 axios 实例（自动携带 token）。
// submitAnswer 是 SSE 流，须用 fetch（见 utils/sse.js），这里仅作转发以保持调用方统一入口。
export const assessment = {
  listPositions: () => api.get('/assessment/positions'),
  createSession: (positionId) => api.post('/assessment/sessions', { position_id: positionId }),
  getSession: (sessionId) => api.get(`/assessment/sessions/${sessionId}`),
  // callbacks: {onDecision, onReply, onDone, onError}；返回 abort() 用于组件卸载时中断
  submitAnswer: (sessionId, questionId, answer, callbacks) =>
    streamAnswer(sessionId, questionId, answer, callbacks),
  getForm: (formId) => api.get(`/assessment/forms/${formId}`),
  submitForm: (sessionId, formType, payload) =>
    api.post(`/assessment/sessions/${sessionId}/forms/submit`, { form_type: formType, payload }),
  // 报告（M6）：异步生成（202）+ 轮询 by-session + 按 id 取 + 异议反馈
  generateReport: (sessionId) => api.post(`/assessment/sessions/${sessionId}/report`),
  getReportBySession: (sessionId) => api.get(`/assessment/reports/by-session/${sessionId}`),
  getReport: (reportId) => api.get(`/assessment/reports/${reportId}`),
  submitFeedback: (reportId, itemId, feedbackText) =>
    api.post(`/assessment/reports/${reportId}/feedback`, { item_id: itemId, feedback_text: feedbackText })
}

// 管理端 P8 测试中心（模块四 M7）接口集合
export const admin = {
  eval: {
    runConsistency: (session_id, runs) => api.post('/admin/eval/consistency', { session_id, runs }),
    runVirtualCandidates: (position_id) => api.post('/admin/eval/virtual-candidates', { position_id }),
    getResult: (task_id) => api.get(`/admin/eval/results/${task_id}`),
    getHistory: () => api.get('/admin/eval/history'),
  },
  trace: {
    list: (filters) => api.get('/admin/trace/list', { params: filters }),
    getDetail: (trace_id) => api.get(`/admin/trace/${trace_id}`),
    getBySession: (session_id) => api.get(`/admin/trace/by-session/${session_id}`),
  },
  feedback: {
    list: (status) => api.get('/admin/feedback/list', { params: { status } }),
    review: (feedback_id, note = '') => api.post(`/admin/feedback/${feedback_id}/review`, { note }),
    badCase: (feedback_id, note = '') => api.post(`/admin/feedback/${feedback_id}/bad-case`, { note }),
  },
}

export default api
