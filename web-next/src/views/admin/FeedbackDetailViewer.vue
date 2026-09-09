<template>
  <teleport to="body">
    <div class="fbd-overlay" @click="close"></div>
    <div class="fbd-panel" role="dialog" aria-modal="true" aria-label="异议详情报告">
      <div class="fbd-head">
        <div class="fbd-head-title">
          <span class="fbd-title">候选人异议 · 报告详情</span>
          <span v-if="detail" class="fbd-sub">{{ detail.std_name || '—' }} · {{ detail.username || '—' }} · {{ formatTime(detail.created_at) }}</span>
        </div>
        <button class="fbd-close" type="button" @click="close">✕ 返回列表</button>
      </div>
      <div class="fbd-body">
        <!-- 拉取中 / 失败（detail 端点 admin-only；404/403 → 明确报错不静默） -->
        <div v-if="error" class="fbd-error">{{ error }}</div>
        <div v-else-if="!detail" class="fbd-loading">正在打开异议详情…</div>
        <!-- 报告整页复用：包裹层挂 candidate + fbd-scope 双类——candidate.css 全部
             选择器以 .candidate 后代形式书写，靠这一层取到暖纸 token 与排版；
             fbd-scope 在 admin body 下重申 token 基准（见 candidate.css 末尾） -->
        <div v-else class="candidate fbd-scope">
          <!-- :key=session_id：detail 换目标报告时强制重挂（Report 的 sessionId 是
               setup 期常量，跨报告复用实例会挂着旧报告数据） -->
          <Report :key="detail.session_id" :session-id="detail.session_id" :fb-detail-data="detail" embedded />
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup>
// 管理端异议详情页内覆盖层（SSOT §22.2 2026-09-09 修订：跳深链改页内嵌入）。
// 数据通路单条：URL 同路由 query ?feedback_id= → detail 端点回溯 session_id →
// 嵌入 Report（props 注入，embedded 态）。点击「详情」、浏览器后退进入、刷新恢复
// 三种入口都落在同一份 query 上，交互一致。
// 对 URL 的写由 TestCenter（打开）与本组件 close（剥 query）分担；本组件只读 route。
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { admin, errMsg } from '../../api'
import { formatTime } from '../../lib/labels'
import Report from '../assessment/Report.vue'

const route = useRoute()
const router = useRouter()

const detail = ref(null)
const error = ref('')

async function load(id) {
  detail.value = null
  error.value = ''
  try {
    const { data } = await admin.feedback.getDetail(id)
    detail.value = data
  } catch (e) {
    error.value = errMsg(e, '异议详情加载失败')
  }
}

// query 在（keep-alive 页原地复用/刷新）→ 拉详情；query 空（后退关闭）由 TestCenter 的 v-if 卸载本组件
watch(
  () => route.query.feedback_id,
  (id) => { if (id) load(String(id)) },
  { immediate: true }
)

function close() {
  // 剥 query 回列表。close=push 正向导航（返回列表），浏览器后退 = 重新打开详情，两侧对称
  router.push({ query: { ...route.query, feedback_id: undefined } })
}

// 打印标记：opened 时 body[data-fbd]，admin.css 打印块据此隐藏测试中心列表（只印报告正文）
onMounted(() => document.body.setAttribute('data-fbd', '1'))
onUnmounted(() => document.body.removeAttribute('data-fbd'))
</script>
