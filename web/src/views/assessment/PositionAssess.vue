<template>
  <div class="grail">
    <!-- 通栏头 -->
    <header class="grail-head">
      <div class="gh-brand">
        <div class="gh-mark">测</div>
        <span class="gh-name">胜任力测评</span>
      </div>
      <div class="gh-divider"></div>
      <div class="gh-crumb">测评端 / <b>{{ model?.position_name || '岗位测评' }}</b></div>
      <div class="gh-actions">
        <button class="btn btn-sm" @click="$router.push('/assessment/positions')">← 返回岗位列表</button>
        <span class="gh-user">{{ auth.user?.username }}</span>
        <button class="btn btn-sm" @click="onLogout">退出</button>
      </div>
    </header>

    <!-- 单栏主体 -->
    <div class="grail-body">
      <main class="rail-center">
        <div class="rc-head">
          <div class="rc-title">{{ model?.position_name || '岗位测评' }}</div>
          <div class="rc-meta" v-if="meta.version">
            <span>模型 v{{ meta.version }}</span>
            <span>已确认</span>
          </div>
        </div>

        <div class="rr-callout grey callout-note">
          以下为该岗位已确认的胜任力模型（只读）。确认无误后点击下方「开始测评」进入交互式问答。
        </div>

        <div v-loading="loading">
          <template v-if="model">
            <!-- 按类目分组展示能力项 -->
            <template v-for="cat in categoryOrder" :key="cat">
              <template v-if="groups[cat]?.length">
                <div class="rc-section">
                  {{ categoryLabel(cat) }}<span class="cnt">{{ groups[cat].length }}</span>
                </div>
                <div class="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>能力项</th>
                        <th style="width:80px">等级</th>
                        <th style="width:90px">重要性</th>
                        <th style="width:90px">权重</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="row in groups[cat]" :key="row.std_name">
                        <td><span class="cell-main">{{ row.std_name }}</span></td>
                        <td class="num">{{ row.required_level != null ? 'Lv' + row.required_level : '—' }}</td>
                        <td>
                          <span class="tag" :class="importanceTagClass(row.importance)">
                            {{ importanceLabel(row.importance) }}
                          </span>
                        </td>
                        <td class="num">{{ pct(row.weight) }}%</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </template>
            </template>

            <!-- 测评入口 -->
            <div class="actions">
              <button class="btn btn-primary btn-lg" :disabled="starting" @click="onStart">
                {{ starting ? '创建会话中…' : '开始测评' }}
              </button>
            </div>
          </template>
        </div>
      </main>
    </div>

    <!-- 通栏脚 -->
    <footer class="grail-foot">
      <span>CF · 测评端</span>
      <div class="f-right"><span>候选人</span></div>
    </footer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api, { assessment } from '../../api'
import { useAuthStore } from '../../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const positionId = route.params.id

const meta = ref({}) // {model_id, version}
const model = ref(null) // {position_name, items[]}
const loading = ref(false)
const starting = ref(false)

const categoryOrder = ['hard_skill', 'soft_skill', 'experience', 'qualification']

// 按类目分组（保持固定顺序）
const groups = computed(() => {
  const g = {}
  for (const it of model.value?.items || []) {
    ;(g[it.category] ||= []).push(it)
  }
  return g
})

// 加载该岗位 confirmed 模型
async function loadModel() {
  loading.value = true
  try {
    const { data } = await api.get(`/assessment/positions/${positionId}/model`)
    meta.value = { model_id: data.model_id, version: data.version }
    model.value = data.model
  } finally {
    loading.value = false
  }
}

// 开始测评：创建会话 -> 跳转对话页
async function onStart() {
  starting.value = true
  try {
    const { data } = await assessment.createSession(positionId)
    const sessionId = data.session_id || data.id
    router.push(`/assessment/session/${sessionId}`)
  } catch (e) {
    if (e.response?.status === 501) {
      ElMessage.warning('测评功能尚未上线（模块二）')
    } else if (e.response?.status === 409) {
      // 开考检查拒绝（readiness 三态）：detail 为 {error_code, message}，取可读中文提示
      const detail = e.response?.data?.detail
      ElMessage.warning(detail?.message || detail || '当前岗位暂不可开考，请联系管理员')
    } else {
      ElMessage.error(e.response?.data?.detail || '创建测评会话失败')
    }
  } finally {
    starting.value = false
  }
}

function onLogout() {
  auth.logout()
  router.push('/login')
}

function categoryLabel(c) {
  return { hard_skill: '硬技能', soft_skill: '软技能', experience: '经验', qualification: '门槛' }[c] || c
}
function importanceLabel(i) {
  return { required: '必备', preferred: '优先', plus: '加分' }[i] || i
}
function importanceTagClass(i) {
  return { required: 'tag-red', preferred: 'tag-amber', plus: 'tag-grey' }[i] || 'tag-grey'
}
// 权重 0-1 小数 -> 百分比整数
function pct(v) {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  return n <= 1 ? (n * 100).toFixed(0) : n.toFixed(0)
}

onMounted(loadModel)
</script>

<style scoped>
.gh-user {
  font-size: 13px;
  color: var(--ink-2);
  align-self: center;
}
.callout-note {
  color: var(--ink-2);
  font-size: 13px;
  cursor: default;
  margin-bottom: 8px;
}
.actions {
  display: flex;
  justify-content: center;
  margin-top: 24px;
}
.btn-lg {
  height: 36px;
  padding: 0 22px;
  font-size: 14px;
}
</style>
