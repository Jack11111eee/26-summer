<template>
  <AdminNav />
  <div class="page">
    <el-card shadow="never" class="panel">
      <div class="head">
        <h2 class="title">能力词典</h2>
        <el-button type="primary" @click="openCreate">+ 新增标准名</el-button>
      </div>

      <!-- 筛选栏 -->
      <div class="filters">
        <el-select v-model="filters.category" placeholder="类目" clearable style="width: 140px">
          <el-option v-for="c in categoryOptions" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
        <el-select v-model="filters.created_by" placeholder="来源" clearable style="width: 130px">
          <el-option label="待确认" value="llm_pending" />
          <el-option label="已确认" value="human" />
        </el-select>
        <el-select v-model="filters.status" placeholder="状态" clearable style="width: 110px">
          <el-option label="启用" value="active" />
          <el-option label="停用" value="disabled" />
        </el-select>
        <el-input v-model="filters.q" placeholder="搜索标准名 / 别名" clearable style="width: 200px"
          @keyup.enter="load" />
        <el-button type="primary" plain @click="load">查询</el-button>
      </div>

      <!-- 词条表格 -->
      <el-table :data="entries" v-loading="loading" stripe>
        <el-table-column prop="std_name" label="标准名" min-width="140" />
        <el-table-column label="类目" width="110">
          <template #default="{ row }">
            <el-tag size="small">{{ categoryLabel(row.category) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="定义" min-width="200">
          <template #default="{ row }">
            <el-tooltip :content="row.definition" placement="top" :show-after="300">
              <span class="ellipsis">{{ row.definition || '—' }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="别名" min-width="160">
          <template #default="{ row }">
            <el-tag v-for="a in row.aliases" :key="a" size="small" class="tag-item">{{ a }}</el-tag>
            <span v-if="!row.aliases?.length" class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="排除项" min-width="140">
          <template #default="{ row }">
            <el-tag v-for="e in row.exclusions" :key="e" size="small" type="info" class="tag-item">{{ e }}</el-tag>
            <span v-if="!row.exclusions?.length" class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.created_by === 'llm_pending'" size="small" type="warning" effect="dark">待确认</el-tag>
            <el-tag v-else size="small" type="info">已确认</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">
              {{ row.status === 'active' ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="openEdit(row)">编辑</el-button>
            <el-button size="small" plain @click="openMerge(row)">合并</el-button>
            <el-popconfirm title="确认删除该词条？" confirm-button-text="删除" cancel-button-text="取消"
              @confirm="onDelete(row)">
              <template #reference>
                <el-button size="small" type="danger" plain>删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无词条" />
        </template>
      </el-table>
    </el-card>

    <!-- 新增对话框 -->
    <el-dialog v-model="createVisible" title="新增标准名" width="560px">
      <el-form :model="createForm" label-width="80px">
        <el-form-item label="标准名" required>
          <el-input v-model="createForm.std_name" placeholder="如：Python" />
        </el-form-item>
        <el-form-item label="类目" required>
          <el-select v-model="createForm.category" style="width: 100%">
            <el-option v-for="c in categoryOptions" :key="c.value" :label="c.label" :value="c.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="定义">
          <el-input v-model="createForm.definition" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="别名">
          <el-select v-model="createForm.aliases" multiple filterable allow-create default-first-option
            placeholder="输入后回车添加" style="width: 100%" />
        </el-form-item>
        <el-form-item label="排除项">
          <el-select v-model="createForm.exclusions" multiple filterable allow-create default-first-option
            placeholder="输入后回车添加" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onCreate">保存</el-button>
      </template>
    </el-dialog>

    <!-- 编辑抽屉（编辑即确认） -->
    <el-drawer v-model="editVisible" :title="`编辑：${editTarget?.std_name}`" size="480px">
      <el-form :model="editForm" label-width="80px">
        <el-form-item label="定义">
          <el-input v-model="editForm.definition" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="别名">
          <el-select v-model="editForm.aliases" multiple filterable allow-create default-first-option
            placeholder="输入后回车添加" style="width: 100%" />
        </el-form-item>
        <el-form-item label="排除项">
          <el-select v-model="editForm.exclusions" multiple filterable allow-create default-first-option
            placeholder="输入后回车添加" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onEditSave">保存（编辑即确认）</el-button>
      </template>
    </el-drawer>

    <!-- 合并对话框 -->
    <el-dialog v-model="mergeVisible" title="合并词条" width="480px">
      <p class="merge-desc">将「{{ mergeSource?.std_name }}」合并到：</p>
      <el-select v-model="mergeTargetKey" filterable placeholder="选择目标条目" style="width: 100%">
        <el-option v-for="e in mergeCandidates" :key="entryKey(e)" :label="`${e.std_name}（${categoryLabel(e.category)}）`"
          :value="entryKey(e)" />
      </el-select>
      <p class="merge-tip">「{{ mergeSource?.std_name }}」将成为目标条目的别名。</p>
      <template #footer>
        <el-button @click="mergeVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!mergeTargetKey" :loading="saving" @click="onMerge">确认合并</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import AdminNav from '../../components/AdminNav.vue'
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'

const categoryOptions = [
  { value: 'hard_skill', label: '硬技能' },
  { value: 'soft_skill', label: '软技能' },
  { value: 'experience', label: '经验' },
  { value: 'qualification', label: '门槛' }
]
function categoryLabel(v) {
  return categoryOptions.find(c => c.value === v)?.label || v
}

const entries = ref([])
const loading = ref(false)
const saving = ref(false)
const filters = reactive({ category: '', created_by: '', status: '', q: '' })

// 加载词条列表
async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/admin/dict', { params: filters })
    entries.value = data
  } finally {
    loading.value = false
  }
}

// ---- 新增 ----
const createVisible = ref(false)
const createForm = reactive({ std_name: '', category: '', definition: '', aliases: [], exclusions: [] })

function openCreate() {
  Object.assign(createForm, { std_name: '', category: '', definition: '', aliases: [], exclusions: [] })
  createVisible.value = true
}

async function onCreate() {
  if (!createForm.std_name || !createForm.category) {
    ElMessage.warning('请填写标准名和类目')
    return
  }
  saving.value = true
  try {
    await api.post('/admin/dict', createForm)
    ElMessage.success('已创建')
    createVisible.value = false
    load()
  } catch (err) {
    if (err.response?.status === 409) {
      ElMessage.error(err.response.data?.detail || '标准名或别名冲突')
    } else {
      ElMessage.error('创建失败')
    }
  } finally {
    saving.value = false
  }
}

// ---- 编辑（编辑即确认） ----
const editVisible = ref(false)
const editTarget = ref(null)
const editForm = reactive({ definition: '', aliases: [], exclusions: [] })

function openEdit(row) {
  editTarget.value = row
  Object.assign(editForm, {
    definition: row.definition || '',
    aliases: [...(row.aliases || [])],
    exclusions: [...(row.exclusions || [])]
  })
  editVisible.value = true
}

async function onEditSave() {
  saving.value = true
  try {
    const { std_name, category } = editTarget.value
    await api.put(`/admin/dict/${encodeURIComponent(std_name)}/${category}`, editForm)
    ElMessage.success('已保存并确认')
    editVisible.value = false
    load()
  } catch (err) {
    if (err.response?.status === 409) {
      ElMessage.error(err.response.data?.detail || '别名冲突')
    } else {
      ElMessage.error('保存失败')
    }
  } finally {
    saving.value = false
  }
}

// ---- 合并 ----
const mergeVisible = ref(false)
const mergeSource = ref(null)
const mergeTargetKey = ref('')

function entryKey(e) {
  return `${e.std_name}::${e.category}`
}

const mergeCandidates = computed(() =>
  entries.value.filter(e => entryKey(e) !== entryKey(mergeSource.value || {}))
)

function openMerge(row) {
  mergeSource.value = row
  mergeTargetKey.value = ''
  mergeVisible.value = true
}

async function onMerge() {
  const target = entries.value.find(e => entryKey(e) === mergeTargetKey.value)
  if (!target) return
  saving.value = true
  try {
    await api.post('/admin/dict/merge', {
      from: { std_name: mergeSource.value.std_name, category: mergeSource.value.category },
      to: { std_name: target.std_name, category: target.category }
    })
    ElMessage.success(`已将「${mergeSource.value.std_name}」合并为「${target.std_name}」的别名`)
    mergeVisible.value = false
    load()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '合并失败')
  } finally {
    saving.value = false
  }
}

// ---- 删除（被引用则仅停用） ----
async function onDelete(row) {
  try {
    const { data } = await api.delete(`/admin/dict/${encodeURIComponent(row.std_name)}/${row.category}`)
    if (data?.status === 'disabled') {
      ElMessage.warning('该词条已被模型引用，已停用')
    } else {
      ElMessage.success('已删除')
    }
    load()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '删除失败')
  }
}

onMounted(load)
</script>

<style scoped>
.page {
  padding: 24px;
}
.panel {
  max-width: 1280px;
  margin: 0 auto;
  border-radius: 12px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.title {
  margin: 0;
  color: #303133;
}
.filters {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.ellipsis {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.tag-item {
  margin: 2px 4px 2px 0;
}
.muted {
  color: #c0c4cc;
}
.merge-desc {
  margin: 0 0 12px;
}
.merge-tip {
  margin: 12px 0 0;
  color: #909399;
  font-size: 13px;
}
</style>
