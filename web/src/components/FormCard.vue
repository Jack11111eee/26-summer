<template>
  <div class="rr-card form-card">
    <div class="form-head">
      <span class="form-title">📎 {{ schema?.title || '信息表单' }}</span>
      <span v-if="submitted" class="tag tag-green">已提交</span>
    </div>

    <div v-loading="loading">
      <el-form
        v-if="schema"
        ref="formRef"
        :model="model"
        :disabled="submitted || submitting"
        label-width="110px"
        label-position="left"
      >
        <el-form-item
          v-for="f in schema.fields"
          :key="f.name"
          :label="f.label"
          :prop="f.name"
          :rules="f.required ? [{ required: true, message: `请填写${f.label}`, trigger: 'blur' }] : []"
        >
          <!-- 文本 / 数字 -->
          <el-input
            v-if="f.type === 'text' || f.type === 'number'"
            v-model="model[f.name]"
            :type="f.type === 'number' ? 'number' : 'text'"
            :placeholder="f.placeholder || ''"
          />
          <!-- 多行文本 -->
          <el-input
            v-else-if="f.type === 'textarea'"
            v-model="model[f.name]"
            type="textarea"
            :rows="3"
            :placeholder="f.placeholder || ''"
          />
          <!-- 下拉选择 -->
          <el-select v-else-if="f.type === 'select'" v-model="model[f.name]" :placeholder="f.placeholder || '请选择'">
            <el-option v-for="opt in f.options || []" :key="opt" :label="opt" :value="opt" />
          </el-select>
          <!-- 日期 -->
          <el-date-picker
            v-else-if="f.type === 'date'"
            v-model="model[f.name]"
            type="date"
            value-format="YYYY-MM-DD"
            :placeholder="f.placeholder || '请选择日期'"
          />
          <!-- 未知类型兜底为单行文本 -->
          <el-input v-else v-model="model[f.name]" :placeholder="f.placeholder || ''" />
        </el-form-item>
      </el-form>

      <div v-else-if="!loading && loadError" class="rr-alert">
        <span>{{ loadError }}</span>
      </div>
    </div>

    <div v-if="!submitted" class="form-actions">
      <button class="btn btn-primary" :disabled="!schema || submitting" @click="onSubmit">
        {{ submitting ? '提交中…' : '提交' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { assessment } from '../api'

const props = defineProps({
  formId: { type: String, required: true },
  sessionId: { type: String, required: true }
})
const emit = defineEmits(['submitted'])

const formRef = ref()
const schema = ref(null) // {form_type, title?, fields:[{name,label,type,required?,options?,placeholder?}]}
const model = reactive({})
const loading = ref(false)
const loadError = ref('')
const submitting = ref(false)
const submitted = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await assessment.getForm(props.formId)
    schema.value = data
    for (const f of data.fields || []) model[f.name] = f.default ?? ''
  } catch (e) {
    loadError.value = e.response?.data?.detail || '表单加载失败'
  } finally {
    loading.value = false
  }
}

async function onSubmit() {
  try {
    await formRef.value.validate()
  } catch {
    return // 校验失败，Element Plus 已就地提示
  }
  submitting.value = true
  try {
    await assessment.submitForm(props.sessionId, schema.value.form_type, { ...model })
    submitted.value = true
    ElMessage.success('表单已提交')
    emit('submitted', { ...model })
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '表单提交失败')
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.form-card {
  margin: 8px 0;
  max-width: 560px;
}
.form-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.form-title {
  font-weight: 600;
  color: var(--ink-1);
  font-size: 14px;
}
.form-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
}
</style>
