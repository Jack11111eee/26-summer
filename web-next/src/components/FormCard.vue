<template>
  <div class="form-card paper-card" style="margin-top: 10px; padding: 18px 20px">
    <template v-if="!schema">
      <p class="field-hint">加载表单中…</p>
    </template>
    <template v-else-if="submitted">
      <p class="field-hint" style="color: var(--chip-ink)">✓ 表单已提交，感谢配合</p>
    </template>
    <form v-else novalidate @submit.prevent="onSubmit">
      <p style="font-weight: 600; font-size: 14px; margin-bottom: 4px">{{ schema.title }}</p>
      <p class="field-hint" style="margin-bottom: 14px">本场测评的最后一步：请如实填写以下核验项。</p>

      <div v-for="f in schema.fields" :key="f.name" class="field">
        <label class="field-label" :for="`ff-${f.name}`">{{ f.label }}<span v-if="f.required" style="color: var(--accent)"> *</span></label>

        <input
          v-if="f.type === 'text' || f.type === 'number' || f.type === 'date'"
          :id="`ff-${f.name}`"
          v-model="payload[f.name]"
          class="input"
          :type="f.type"
          :placeholder="f.placeholder"
          :required="f.required"
        />
        <textarea
          v-else-if="f.type === 'textarea'"
          :id="`ff-${f.name}`"
          v-model="payload[f.name]"
          class="textarea"
          :placeholder="f.placeholder"
          :required="f.required"
        />
        <select
          v-else-if="f.type === 'select'"
          :id="`ff-${f.name}`"
          v-model="payload[f.name]"
          class="select"
          :required="f.required"
        >
          <option v-if="!f.required" value="">（未选择）</option>
          <option v-for="o in normOptions(f.options)" :key="String(o.value)" :value="o.value">{{ o.label ?? o.value }}</option>
        </select>

        <!-- v2 勾选组（facet major_group/长尾 fallback）：勾 = 是；提交收集为数组 -->
        <div v-else-if="f.type === 'checklist'" class="checklist">
          <label
            v-for="o in normOptions(f.options)"
            :key="String(o.value)"
            class="check-row"
          >
            <input
              type="checkbox"
              :value="o.value"
              :checked="checkedSet(f.name).has(o.value)"
              @change="toggleChecked(f.name, o.value)"
            />
            <span>{{ o.label ?? o.value }}</span>
          </label>
          <p class="field-hint">勾选符合的项；未勾选项将按「否」提交。</p>
        </div>
      </div>

      <p v-if="errorText" class="field-error">{{ errorText }}</p>
      <button class="btn-accent" style="width: auto; padding: 9px 26px" type="submit" :disabled="submitting">
        {{ submitting ? '提交中…' : '提交表单' }}
      </button>
    </form>
  </div>
</template>

<script setup>
// 资格核验表单（gate 分支）：初始 schema 可由父级传入（刷新恢复 open_form），
// 否则按 formId 拉取；提交走 submit-v2（expected_revision 先固定 1——渲染实例唯一）。
import { onMounted, reactive, ref, toRaw } from 'vue'
import { assessment, errMsg } from '../api'
import { toast } from './ui'

const props = defineProps({
  formId: { type: String, required: true },
  sessionId: { type: String, required: true },
  initialSchema: { type: Object, default: null }
})
const emit = defineEmits(['submitted'])

const schema = ref(props.initialSchema || null)
const payload = reactive({})
// checklist 勾选组独立载体（field.name → Set；v2 facet 勾选组，提交时展开为数组塞回 payload）
const checklists = reactive({})
const submitted = ref(false)
const submitting = ref(false)
const errorText = ref('')

onMounted(async () => {
  if (schema.value) {
    seedDefaults()
    return
  }
  try {
    const { data } = await assessment.getForm(props.formId)
    schema.value = data
    seedDefaults()
  } catch (e) {
    errorText.value = errMsg(e, '表单加载失败')
  }
})

function seedDefaults() {
  for (const f of schema.value.fields || []) {
    if (f.type === 'checklist') {
      checklists[f.name] = new Set()
      payload[f.name] = []
    } else if (f.type === 'select') payload[f.name] = null
    else if (f.type === 'number') payload[f.name] = null
    else payload[f.name] = ''
  }
}

function checkedSet(name) {
  return checklists[name] || new Set()
}

function toggleChecked(name, value) {
  const set = checkedSet(name)
  if (set.has(value)) set.delete(value)
  else set.add(value)
  // 同步进 payload（提交载体）——Set 不可 JSON 序列化，展开为数组
  payload[name] = [...set]
}

// options 兼容两种形态：纯字符串数组（后端 forms.py 生成）与 {value,label} 对象数组
function normOptions(opts) {
  return (opts || []).map((o) => (typeof o === 'string' ? { value: o, label: o } : o))
}

function validate() {
  for (const f of schema.value.fields || []) {
    if (!f.required) continue
    const v = payload[f.name]
    if (v === null || v === undefined || String(v).trim() === '') {
      errorText.value = `「${f.label}」为必填项`
      return false
    }
    if (f.type === 'select' && v === '') {
      errorText.value = `请选择「${f.label}」`
      return false
    }
  }
  errorText.value = ''
  return true
}

async function onSubmit() {
  if (submitting.value || submitted.value) return
  if (!validate()) return
  submitting.value = true
  try {
    const { data } = await assessment.submitForm(props.sessionId, props.formId, { ...toRaw(payload) }, 1)
    submitted.value = true
    toast('表单已提交')
    // submit-v2 响应透传父级（action: finish/next/form——完赛收尾由 Chat 按 finish 跳报告页）
    emit('submitted', data)
  } catch (e) {
    const code = e?.response?.data?.detail?.error_code
    if (code === 'FORM_ALREADY_SUBMITTED') {
      submitted.value = true // 幂等重放：按已提交处理
      toast('该表单已提交过')
      emit('submitted') // 无 action 数据：父级走 refreshSession 兜底（不为幂等重放强造 finish 跳转）
    } else if (code === 'FORM_INSTANCE_REVISION_CONFLICT') {
      errorText.value = '表单已更新，正在重新加载…'
      try {
        const { data } = await assessment.getForm(props.formId)
        schema.value = data
        seedDefaults()
        errorText.value = ''
      } catch { /* keep */ }
    } else {
      errorText.value = errMsg(e, '提交失败，请重试')
    }
  } finally {
    submitting.value = false
  }
}
</script>
