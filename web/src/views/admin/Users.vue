<template>
  <AdminNav />
  <div class="page">
    <el-card shadow="never" class="panel">
      <div class="head">
        <h2 class="title">用户管理</h2>
        <el-button type="primary" @click="createVisible = true">+ 新建账号</el-button>
      </div>

      <el-table :data="users" v-loading="loading" stripe>
        <el-table-column prop="username" label="用户名" min-width="140" />
        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.role === 'admin' ? 'danger' : 'primary'" effect="plain">
              {{ row.role === 'admin' ? '管理员' : '候选人' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_active ? 'success' : 'info'">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openReset(row)">重置密码</el-button>
            <el-button
              size="small"
              :type="row.is_active ? 'warning' : 'success'"
              :disabled="row.username === auth.user?.username && row.is_active"
              @click="onToggleActive(row)"
            >
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无用户" /></template>
      </el-table>
    </el-card>

    <!-- 新建账号 -->
    <el-dialog v-model="createVisible" title="新建账号" width="420px" @closed="resetCreate">
      <el-form label-width="80px">
        <el-form-item label="用户名" required>
          <el-input v-model="createForm.username" placeholder="登录用户名" />
        </el-form-item>
        <el-form-item label="密码" required>
          <el-input v-model="createForm.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="createForm.role">
            <el-radio value="candidate">候选人</el-radio>
            <el-radio value="admin">管理员</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码 -->
    <el-dialog v-model="resetVisible" :title="`重置密码 · ${resetTarget?.username}`" width="380px">
      <el-input v-model="resetPassword" type="password" show-password placeholder="新密码（至少 6 位）" />
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetting" @click="onReset">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import AdminNav from '../../components/AdminNav.vue'
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const users = ref([])
const loading = ref(false)

const createVisible = ref(false)
const creating = ref(false)
const createForm = reactive({ username: '', password: '', role: 'candidate' })

const resetVisible = ref(false)
const resetting = ref(false)
const resetTarget = ref(null)
const resetPassword = ref('')

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/admin/users')
    users.value = data
  } finally {
    loading.value = false
  }
}

async function onCreate() {
  if (!createForm.username.trim() || createForm.password.length < 6) {
    ElMessage.warning('用户名必填，密码至少 6 位')
    return
  }
  creating.value = true
  try {
    await api.post('/admin/users', { ...createForm })
    ElMessage.success('已创建')
    createVisible.value = false
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

async function onToggleActive(row) {
  try {
    await api.patch(`/admin/users/${row.user_id}`, { is_active: !row.is_active })
    ElMessage.success(row.is_active ? '已停用' : '已启用')
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

function openReset(row) {
  resetTarget.value = row
  resetPassword.value = ''
  resetVisible.value = true
}

async function onReset() {
  if (resetPassword.value.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  resetting.value = true
  try {
    await api.patch(`/admin/users/${resetTarget.value.user_id}`, { password: resetPassword.value })
    ElMessage.success('密码已重置')
    resetVisible.value = false
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '重置失败')
  } finally {
    resetting.value = false
  }
}

function resetCreate() {
  createForm.username = ''
  createForm.password = ''
  createForm.role = 'candidate'
}

function formatTime(iso) {
  return iso ? new Date(iso).toLocaleString('zh-CN', { hour12: false }) : '—'
}

onMounted(load)
</script>

<style scoped>
.page {
  padding: 24px;
}
.panel {
  max-width: 960px;
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
</style>
