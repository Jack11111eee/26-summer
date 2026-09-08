import axios from 'axios'
import { toast } from '../components/ui'
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
        toast('登录状态已失效，请重新登录', 'error')
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

// 后端错误 detail 兼容形态：字符串 或 {error_code, message}（WR-01 约定）
export function errMsg(e, fallback = '请求失败') {
  const d = e?.response?.data?.detail
  if (typeof d === 'string' && d) return d
  if (d?.message) return d.message
  return fallback
}

// 测评端（模块二/三）接口集合。除流式作答外均走上方 axios 实例（自动携带 token）。
export const assessment = {
  listPositions: () => api.get('/assessment/positions'),
  getModel: (positionId) => api.get(`/assessment/positions/${positionId}/model`),
  // get-or-create（SSOT §12.1）：无在途 201 新建 / 同岗位在途 200 复用同 session_id
  createSession: (positionId) => api.post('/assessment/sessions', { position_id: positionId }),
  // 历史端点（SSOT §12.6）：本人会话列表，服务端分页 {items,total} + status 过滤
  listSessions: (params) => api.get('/assessment/sessions', { params }),
  // 入场确认（SC-5 计时起算锚）：PENDING_START → ACTIVE；409 SESSION_ALREADY_ACTIVE 幂等
  startSession: (sessionId) => api.post(`/assessment/sessions/${sessionId}/start`),
  // 暂停/继续（03-05 交付，web-next 首次接线）：409 SESSION_ALREADY_PAUSED / SESSION_NOT_PAUSED 幂等护栏
  pauseSession: (sessionId) => api.post(`/assessment/sessions/${sessionId}/pause`),
  resumeSession: (sessionId) => api.post(`/assessment/sessions/${sessionId}/resume`),
  getSession: (sessionId) => api.get(`/assessment/sessions/${sessionId}`),
  // callbacks: {onDecision, onReply, onDone, onError}；返回 abort() 用于组件卸载时中断
  submitAnswer: (sessionId, questionId, answer, callbacks) =>
    streamAnswer(sessionId, questionId, answer, callbacks),
  getForm: (formId) => api.get(`/assessment/forms/${formId}`),
  submitForm: (sessionId, formInstanceId, payload, expectedRevision = 1) =>
    api.post(`/assessment/sessions/${sessionId}/forms/submit-v2`, {
      form_instance_id: formInstanceId,
      payload,
      expected_revision: expectedRevision,
      schema_version: 'v1'
    }),
  // 报告（M6）：异步生成（202）+ 轮询 by-session + 按 id 取 + 异议反馈
  generateReport: (sessionId) => api.post(`/assessment/sessions/${sessionId}/report`),
  getReportBySession: (sessionId) => api.get(`/assessment/reports/by-session/${sessionId}`),
  submitFeedback: (reportId, itemId, feedbackText) =>
    api.post(`/assessment/reports/${reportId}/feedback`, { item_id: itemId, feedback_text: feedbackText }),
  // 意见反馈通道（SSOT §22.1）：提交 + 本人历史（含处理状态）
  submitSuggestion: (text) => api.post('/assessment/suggestions', { text }),
  listMySuggestions: () => api.get('/assessment/suggestions')
}

// 管理端（模块一：岗位库/JD 导入）
export const adminPositions = {
  getTodos: () => api.get('/admin/todos'),
  listPositions: (params) => api.get('/admin/positions', { params }),
  listPending: (params) => api.get('/admin/positions/pending', { params }),
  reviewPosition: (positionId, action) => api.post(`/admin/positions/${positionId}/review`, { action }),
  listOrphanJds: (params) => api.get('/admin/jds/orphan', { params }),
  reassignJd: (jdId, positionId) => api.post(`/admin/jds/${jdId}/reassign`, { position_id: positionId }),
  positionOptions: () => api.get('/admin/positions/options'),
  listJds: (positionId) => api.get(`/admin/positions/${positionId}/jds`),
  jdDetail: (jdId) => api.get(`/admin/jds/${jdId}`),
  reparseJd: (jdId) => api.post(`/admin/jds/${jdId}/reparse`),
  importJd: (jdText, company) => api.post('/admin/jds/import', { jd_text: jdText, company }),
  importJdFile: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/admin/jds/import-file', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  }
}

// 管理端（模型审核/版本/题库）
export const adminModels = {
  aggregate: (positionId) => api.post(`/admin/positions/${positionId}/aggregate`),
  getAggregateProgress: (positionId) => api.get(`/admin/positions/${positionId}/aggregate/progress`),
  getModel: (positionId) => api.get(`/admin/positions/${positionId}/model`),
  updateModel: (modelId, items) => api.put(`/admin/models/${modelId}`, { items }),
  confirmModel: (modelId) => api.post(`/admin/models/${modelId}/confirm`),
  retryQuestionBankTask: (taskId) => api.post(`/admin/question-bank-tasks/${taskId}/retry`),
  retryLevel: (positionId) => api.post(`/admin/positions/${positionId}/retry-level`, { action: 'retry' }),
  markEvidenceExclusion: (positionId, body) => api.post(`/admin/positions/${positionId}/evidence-exclusions`, body),
  liftEvidenceExclusion: (positionId, body) => api.delete(`/admin/positions/${positionId}/evidence-exclusions`, { data: body }),
  listEvidenceExclusions: (positionId) => api.get(`/admin/positions/${positionId}/evidence-exclusions`),
  listVersions: (positionId) => api.get(`/admin/positions/${positionId}/versions`),
  diffModels: (newId, againstId) => api.get(`/admin/models/${newId}/diff`, { params: { against: againstId } })
}

// 管理端（词典）
export const adminDict = {
  list: (params) => api.get('/admin/dict', { params }),
  create: (body) => api.post('/admin/dict', body),
  update: (stdName, category, body) => api.put(`/admin/dict/${encodeURIComponent(stdName)}/${category}`, body),
  merge: (from, to) => api.post('/admin/dict/merge', { from, to }),
  remove: (stdName, category) => api.delete(`/admin/dict/${encodeURIComponent(stdName)}/${category}`)
}

// 管理端（题库状态，SSOT §9.5）：任务列表 / 详情 / 题目表 / retry（接线既有端点）
export const adminQbank = {
  list: (params) => api.get('/admin/question-bank-tasks', { params }),
  detail: (taskId) => api.get(`/admin/question-bank-tasks/${taskId}`),
  questions: (taskId, params) => api.get(`/admin/question-bank-tasks/${taskId}/questions`, { params }),
  retry: (taskId) => api.post(`/admin/question-bank-tasks/${taskId}/retry`)
}

// 管理端（用户）
export const adminUsers = {
  list: (params) => api.get('/admin/users', { params }),
  create: (body) => api.post('/admin/users', body),
  patch: (userId, body) => api.patch(`/admin/users/${userId}`, body)
}

// 管理端（测试中心 M7 + 报告发布）
export const admin = {
  eval: {
    runConsistency: (sessionId, runs) => api.post('/admin/eval/consistency', { session_id: sessionId, runs }),
    runVirtualCandidates: (positionId) => api.post('/admin/eval/virtual-candidates', { position_id: positionId }),
    getResult: (taskId) => api.get(`/admin/eval/results/${taskId}`),
    getHistory: (limit = 20) => api.get('/admin/eval/history', { params: { limit } })
  },
  trace: {
    list: (params) => api.get('/admin/trace/list', { params }),
    getDetail: (traceId) => api.get(`/admin/trace/${traceId}`),
    getBySession: (sessionId) => api.get(`/admin/trace/by-session/${sessionId}`)
  },
  feedback: {
    list: (status) => api.get('/admin/feedback/list', { params: status ? { status } : {} }),
    review: (feedbackId, note = '') => api.post(`/admin/feedback/${feedbackId}/review`, { note }),
    badCase: (feedbackId, note = '') => api.post(`/admin/feedback/${feedbackId}/bad-case`, { note })
  },
  // 意见反馈（SSOT §22.1——独立 suggestion 通道，管理端 TestCenter 反馈区切换）
  suggestions: {
    list: (status) => api.get('/admin/suggestions', { params: status ? { status } : {} }),
    review: (suggestionId, note = '') => api.post(`/admin/suggestions/${suggestionId}/review`, { note })
  },
  reports: {
    publish: (reportId, reviewOutcome = 'CONFIRMED', reviewNote = '') =>
      api.post(`/admin/reports/${reportId}/publish`, { review_outcome: reviewOutcome, review_note: reviewNote })
  }
}

export default api
