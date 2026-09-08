<template>
  <div class="page">
    <div class="page-head">
      <div class="open-head serif">
        <div class="kicker">FEEDBACK · 意见反馈</div>
        <h1>告诉我们你的想法</h1>
        <p>对系统的任何建议——体验、题目质量、流程——都会进入人工处理队列，处理结果会显示在下方记录里。</p>
      </div>
    </div>

    <div class="page-inner feedback-inner">
      <!-- 提交表单 -->
      <div class="paper-card">
        <div class="field">
          <label class="field-label" for="suggestion-text">意见内容</label>
          <textarea
            id="suggestion-text"
            v-model="text"
            class="textarea"
            rows="5"
            maxlength="2000"
            placeholder="例如：希望在报告页增加导出 PDF 的按钮…（2000 字以内）"
            :disabled="submitting"
          ></textarea>
          <span v-if="textError" class="field-error">{{ textError }}</span>
          <span class="field-hint">提交后可在下方查看处理进度；内容不超过 2000 字。</span>
        </div>
        <button class="btn-accent fb-submit" :disabled="submitting || !text.trim()" @click="submit">
          {{ submitting ? '提交中…' : '提交意见' }}
        </button>
      </div>

      <!-- 本人历史 -->
      <div class="hist-section">
        <h4 class="serif">我的反馈记录</h4>
        <div v-if="loading" class="empty" style="padding: 24px 0">加载记录中…</div>
        <div v-else-if="!mySuggestions.length" class="empty" style="padding: 24px 0">
          <p class="serif" style="font-size: 15px">还没有反馈记录</p>
          <p style="font-size: 13px">提交的第一条意见会显示在这里。</p>
        </div>
        <div v-else class="sug-list">
          <div v-for="s in mySuggestions" :key="s.suggestion_id" class="sug-item">
            <div class="sug-head">
              <span v-if="s.status === 'pending'" class="chip amber">待处理</span>
              <span v-else class="chip chip-done">已处理</span>
              <span class="field-hint">{{ formatTime(s.created_at) }}</span>
            </div>
            <p class="sug-text">{{ s.text }}</p>
            <div v-if="s.status === 'reviewed' && s.review_note" class="sug-note">
              <b>处理备注</b>
              <p>{{ s.review_note }}</p>
              <span class="field-hint">{{ formatTime(s.reviewed_at) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// 意见反馈页（SSOT §22.1）：提交（空/超长 422 toast）+ 本人历史（待处理/已处理状态
// 标签 + 处理备注展示）。独立于报告页的逐分异议（feedback 通道）。
import { onActivated, onMounted, ref } from 'vue'
import { assessment, errMsg } from '../../api'
import { toast } from '../../components/ui'
import { formatTime } from '../../lib/labels'

defineOptions({ name: 'AssessmentFeedback' }) // 壳内 keep-alive include 依名匹配（§5，2026-09-08）

const text = ref('')
const textError = ref('')
const submitting = ref(false)
const loading = ref(false)
const mySuggestions = ref([])

async function submit() {
  const body = text.value.trim()
  if (!body) {
    textError.value = '请填写反馈内容'
    return
  }
  submitting.value = true
  textError.value = ''
  try {
    await assessment.submitSuggestion(body)
    toast('意见已提交，我们将人工处理')
    text.value = ''
    await loadMine()
  } catch (e) {
    // 422（空/超长）与其他错误一律 toast 可读文案
    toast(errMsg(e, '提交失败，请稍后再试'), 'error')
  } finally {
    submitting.value = false
  }
}

async function loadMine() {
  loading.value = true
  try {
    const { data } = await assessment.listMySuggestions()
    mySuggestions.value = data
  } catch (e) {
    toast(errMsg(e, '反馈记录加载失败'), 'error')
  } finally {
    loading.value = false
  }
}

onMounted(loadMine)

// keep-alive 激活：静默重拉处理进度（booted 守卫防首屏双拉；草稿文本由页面缓存天然
// 保留，不重置，§5，2026-09-08）
let booted = false
onActivated(() => {
  if (!booted) { booted = true; return }
  loadMine()
})
</script>
