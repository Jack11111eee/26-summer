// 提交答案并消费回复（模块二测评对话）
//
// 后端两种可能形态，本函数自适应：
//   A. SSE 流（07 文档 §7.1 目标形态，Content-Type: text/event-stream）
//        data: {type:'decision', action, reason, score_live}
//        data: {type:'reply', content:'...'}   （逐 token）
//        data: {type:'done', next_question_id?}
//   B. 单次 JSON（当前后端实现，Content-Type: application/json）
//        {action, reply, question_id, next_question_id, score_live}
//      —— 无流式，一次性返回完整 reply；映射为 decision + 整段 reply + done 回调。
//
// 用 fetch + ReadableStream 而非 EventSource：POST + Bearer Header EventSource 不支持。
//
// callbacks: {onDecision, onReply, onDone, onError}
// 返回一个 abort() 函数，组件卸载时可中断（仅对流式形态有意义）。

export function streamAnswer(sessionId, questionId, answer, callbacks) {
  const { onDecision, onReply, onDone, onError } = callbacks
  const controller = new AbortController()

  fetch(`/api/assessment/sessions/${sessionId}/answer`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${localStorage.getItem('token') || ''}`
    },
    body: JSON.stringify({ question_id: questionId, answer }),
    signal: controller.signal
  })
    .then(async (response) => {
      if (!response.ok) {
        // 与 axios 拦截器对齐的错误形态（WR-01：后端 409 detail 为 {error_code, message} 时取可读 message）
        let detail = `请求失败（${response.status}）`
        try {
          const body = await response.json()
          if (body?.detail?.message) detail = body.detail.message
          else if (body?.detail) detail = body.detail
        } catch {
          /* 非 JSON 响应体，保留默认提示 */
        }
        throw new Error(detail)
      }

      const contentType = response.headers.get('Content-Type') || ''

      // ---- 形态 B：单次 JSON（当前后端）----
      if (contentType.includes('application/json')) {
        const data = await response.json()
        onDecision?.({ action: data.action, score_live: data.score_live, reason: data.reason })
        if (data.reply) onReply?.(data.reply)
        onDone?.({ action: data.action, next_question_id: data.next_question_id })
        return
      }

      // ---- 形态 A：SSE 流（目标形态）----
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = '' // 跨 chunk 的半行缓存

      const pump = () =>
        reader.read().then(({ done, value }) => {
          if (done) return

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() // 最后一段可能是不完整行，留给下一轮拼接

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            let data
            try {
              data = JSON.parse(line.slice(6))
            } catch {
              continue // 跳过无法解析的行，不中断整条流
            }
            if (data.type === 'decision') onDecision?.(data)
            else if (data.type === 'reply') onReply?.(data.content)
            else if (data.type === 'done') onDone?.(data)
          }

          return pump()
        })

      return pump()
    })
    .catch((err) => {
      if (err.name === 'AbortError') return // 主动中断不算错误
      onError?.(err)
    })

  return () => controller.abort()
}
