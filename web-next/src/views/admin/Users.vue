<template>
  <div>
    <header class="topbar">
      <div>
        <div class="topbar-title">用户<span>管理</span></div>
        <div class="topbar-meta">{{ total }} USERS</div>
      </div>
      <div class="topbar-actions">
        <button class="btn" :disabled="loading" @click="load">刷新</button>
        <button class="btn primary" @click="openCreate">＋ 建号</button>
      </div>
    </header>

    <section class="block n2">
      <div class="block-head">
        <span class="block-title">用户清单</span>
        <span class="block-cnt">{{ total }} 条</span>
      </div>
      <table>
        <thead>
          <tr><th style="width: 26%">username</th><th style="width: 16%">role</th><th style="width: 16%">is_active</th><th style="width: 22%">created_at</th><th style="width: 20%; text-align: right">action</th></tr>
        </thead>
        <tbody>
          <tr v-for="u in items" :key="u.user_id">
            <td v-clip><span class="cell-main">{{ u.username }}</span></td>
            <td>
              <span v-if="u.role === 'admin'" class="tag tag-solid">ADMIN</span>
              <span v-else class="tag">CANDIDATE</span>
            </td>
            <td>
              <span v-if="u.is_active" class="tag tag-soft">启用</span>
              <span v-else class="tag tag-red">停用</span>
            </td>
            <td>{{ formatTime(u.created_at) }}</td>
            <td>
              <div class="row-actions">
                <button class="row-btn" @click="openReset(u)">重置密码</button>
                <button
                  class="row-btn"
                  :class="u.is_active ? 'row-btn-danger' : 'row-btn-solid'"
                  :disabled="isSelf(u) && u.is_active"
                  @click="toggleActive(u)"
                >
                  {{ u.is_active ? '停用' : '启用' }}
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="!items.length && !loading"><td colspan="5" class="empty-row">暂无用户</td></tr>
        </tbody>
      </table>
      <UiPager v-model:page="page" v-model:page-size="pageSize" :total="total" @change="load" />
    </section>

    <!-- 建号 -->
    <UiModal
      v-if="createState.show"
      title="新建账号"
      sub="注册通道之外的补充入口（可建管理员）"
      @close="createState.show = false"
      @confirm="doCreate"
    >
      <div class="field">
        <label class="field-label">用户名</label>
        <input v-model="createState.username" class="input" :class="{ invalid: createState.err && !createState.username.trim() }" type="text" />
      </div>
      <div class="field">
        <label class="field-label">密码</label>
        <input v-model="createState.password" class="input" type="password" placeholder="至少 6 位" />
        <span v-if="createState.err" class="field-error">{{ createState.err }}</span>
      </div>
      <div class="radio-row" style="margin-top: 4px">
        <label><input v-model="createState.role" type="radio" value="candidate" /> 考生</label>
        <label><input v-model="createState.role" type="radio" value="admin" /> 管理员</label>
      </div>
    </UiModal>

    <!-- 重置密码 -->
    <UiModal
      v-if="resetState.show"
      :title="`重置密码 · ${resetState.user?.username}`"
      sub="重置后原密码立即失效"
      @close="resetState.show = false"
      @confirm="doReset"
    >
      <div class="field">
        <label class="field-label">新密码</label>
        <input v-model="resetState.password" class="input" type="password" placeholder="至少 6 位" />
        <span v-if="resetState.err" class="field-error">{{ resetState.err }}</span>
      </div>
    </UiModal>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { adminUsers, errMsg } from '../../api'
import { UiPager, UiModal, toast } from '../../components/ui'
import { useAuthStore } from '../../stores/auth'
import { formatTime } from '../../lib/labels'

const auth = useAuthStore()

const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)

const createState = reactive({ show: false, username: '', password: '', role: 'candidate', err: '' })
const resetState = reactive({ show: false, user: null, password: '', err: '' })

function isSelf(u) {
  return u.username === auth.user?.username
}

async function load() {
  loading.value = true
  try {
    const { data } = await adminUsers.list({ page: page.value, page_size: pageSize.value })
    items.value = data.items
    total.value = data.total
  } catch (e) {
    toast(errMsg(e, '用户列表加载失败'), 'error')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(createState, { show: true, username: '', password: '', role: 'candidate', err: '' })
}

async function doCreate() {
  if (!createState.username.trim()) {
    createState.err = '用户名必填'
    return
  }
  if (createState.password.length < 6) {
    createState.err = '密码至少 6 位'
    return
  }
  createState.err = ''
  try {
    await adminUsers.create({
      username: createState.username.trim(),
      password: createState.password,
      role: createState.role
    })
    toast('账号已创建')
    createState.show = false
    await load()
  } catch (e) {
    createState.err = errMsg(e, '创建失败')
  }
}

function openReset(u) {
  Object.assign(resetState, { show: true, user: u, password: '', err: '' })
}

async function doReset() {
  if (resetState.password.length < 6) {
    resetState.err = '密码至少 6 位'
    return
  }
  resetState.err = ''
  try {
    await adminUsers.patch(resetState.user.user_id, { password: resetState.password })
    toast('密码已重置')
    resetState.show = false
  } catch (e) {
    resetState.err = errMsg(e, '重置失败')
  }
}

async function toggleActive(u) {
  try {
    await adminUsers.patch(u.user_id, { is_active: !u.is_active })
    toast(`「${u.username}」已${u.is_active ? '停用' : '启用'}`)
    u.is_active = !u.is_active
  } catch (e) {
    toast(errMsg(e, '操作失败'), 'error')
  }
}

load()
</script>
