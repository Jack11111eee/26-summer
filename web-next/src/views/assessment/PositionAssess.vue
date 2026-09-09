<template>
  <div class="page">
    <div class="page-inner" style="max-width: 780px">
      <span class="back-link" @click="goBack">← {{ isPreview ? '返回测评历史' : '返回岗位选择' }}</span>

      <div class="open-head serif" style="margin-bottom: 26px">
        <div class="kicker">{{ model?.position_name || 'ASSESSMENT' }} · 模型 v{{ model?.version ?? '—' }}</div>
        <h1>{{ model?.position_name || '岗位胜任力模型' }}</h1>
        <p>{{ isPreview ? '这是该岗位当前考察的能力项，仅供回看。' : '开考前请浏览该岗位考察的能力项。正式作答时我会根据你的经历动态追问，无需死记这些条目。' }}</p>
      </div>

      <div v-if="loading" class="empty">加载模型中…</div>
      <div v-else-if="!model" class="empty">
        <p class="serif">暂不可开考</p>
        <p style="font-size: 13px">{{ loadErr || '该岗位暂无已确认模型' }}</p>
      </div>

      <template v-else>
        <div v-for="cat in CATEGORY_ORDER" :key="cat.key" class="model-block">
          <h4><span class="tb-badge">{{ cat.label }}</span> <span style="color: var(--ink-3); font-size: 12px">{{ catItems(cat.key).length }} 项</span></h4>
          <table v-if="catItems(cat.key).length">
            <thead>
              <tr><th style="width: 52%">能力项</th><th style="width: 12%">等级</th><th style="width: 18%">重要性</th><th class="num" style="width: 18%">权重</th></tr>
            </thead>
            <tbody>
              <tr v-for="it in catItems(cat.key)" :key="it.std_name">
                <td>{{ it.std_name }} <span v-if="it.gate" class="chip amber" style="margin-left: 6px">门槛</span></td>
                <td>{{ it.required_level ? `Lv${it.required_level}` : '—' }}</td>
                <td>{{ importanceLabel(it.importance) }}</td>
                <td class="num">{{ pct(it.weight) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 预览态（§12.6，2026-09-08）：只读回看——底部开始块与时长提示整体隐藏，
             不再作开考入口（历史 completed 行「评估模型」直达本态）；开考流程走岗位选择页 -->
        <template v-if="!isPreview">
          <hr class="divider" />

          <div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap">
            <p class="field-hint" style="flex: 1; min-width: 220px">共 {{ totalCount }} 项能力 · 约 40 分钟 · 从点击「开始测评」起计时</p>
            <button class="btn-accent" style="width: auto; padding: 11px 34px" :disabled="starting" @click="startAssessment">
              {{ starting ? '正在创建测评…' : (hasActiveResume ? '继续测评（从中断处继续）' : '开始测评') }}
            </button>
          </div>
        </template>
        <p v-else class="field-hint" style="margin-top: 8px">共 {{ totalCount }} 项能力</p>
      </template>
    </div>
  </div>
</template>

<script setup>
// 岗位开考页：confirmed 模型预览 + 建会话（readiness 409 → 友好提示）。
// preview=1 只读预览态（SSOT §12.6，2026-09-08）：历史 completed 行「评估模型」直达——
// 隐藏底部开始块与时长提示、返回链接指向测评历史页；开考入口保持在岗位选择页
// （预览的不是场次锚定版本而是当前最新 confirmed 模型——既有语义不变）。模型加载
// 失败（404 岗位下架等）保持现有错误展示。
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { assessment, errMsg } from '../../api'
import { toast } from '../../components/ui'
import { CATEGORY_ORDER_HELP, importanceLabel, pct } from '../../lib/labels'

const CATEGORY_ORDER = CATEGORY_ORDER_HELP
const route = useRoute()
const router = useRouter()
const positionId = route.params.id
// 只读预览态：?preview=1（query 为字符串——与 resume 标记同形）
const isPreview = computed(() => route.query.preview === '1')

const model = ref(null)
const loading = ref(false)
const loadErr = ref('')
const starting = ref(false)

const totalCount = computed(() => model.value?.model?.items?.length ?? 0)

// 按钮态（§12.6）：岗位卡片携带 resume 标记（进行中会话存在）→ 标注「继续测评（从中断处
// 继续）」；后端 get-or-create 已保证两种点击语义等价（缺标记时回退「开始测评」，点击
// 仍会复用在途会话），最简实现不新增后端请求
const hasActiveResume = computed(() => route.query.resume === '1' || route.query.resume === 1)

function catItems(cat) {
  return (model.value?.model?.items || []).filter((it) => it.category === cat)
}

function goBack() {
  router.push(isPreview.value ? '/assessment/history' : '/assessment/positions')
}

async function startAssessment() {
  if (starting.value) return
  starting.value = true
  try {
    const { data } = await assessment.createSession(positionId)
    router.push(`/assessment/session/${data.session_id}`)
  } catch (e) {
    // readiness 三态 409：{error_code, message} —— message 已是面向考生的中文文案
    toast(errMsg(e, '暂时无法开考，请稍后再试'), 'error')
  } finally {
    starting.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    const { data } = await assessment.getModel(positionId)
    model.value = data
  } catch (e) {
    loadErr.value = errMsg(e, '')
    if (e?.response?.status !== 404) {
      toast(errMsg(e, '模型加载失败'), 'error')
    }
  } finally {
    loading.value = false
  }
})
</script>
