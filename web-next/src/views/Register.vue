<template>
  <button class="page-theme" type="button" :title="isDark ? '切换到日间' : '切换到夜间'" @click="toggleTheme">{{ isDark ? '日间' : '夜间' }}</button>
  <div class="page">
    <div class="page-head">
      <div class="open-head serif">
        <div class="kicker">CREATE ACCOUNT</div>
        <h1>注册考生账号</h1>
        <p>注册后即可开始岗位胜任力测评。管理员账号由系统管理员在后台创建。</p>
      </div>
    </div>

    <div class="page-inner">
      <form class="paper-card" novalidate @submit.prevent="onSubmit">
        <div class="field">
          <label class="field-label" for="reg-username">用户名</label>
          <input id="reg-username" v-model="username" class="input" type="text" autocomplete="username" />
        </div>
        <div class="field">
          <label class="field-label" for="reg-password">密码</label>
          <input id="reg-password" v-model="password" class="input" type="password" autocomplete="new-password" />
          <span class="field-hint">至少 6 位</span>
        </div>
        <div class="field">
          <label class="field-label" for="reg-confirm">确认密码</label>
          <input id="reg-confirm" v-model="confirm" class="input" type="password" autocomplete="new-password" />
        </div>
        <p v-if="errorText" class="field-error">{{ errorText }}</p>
        <button class="btn-accent" type="submit" :disabled="submitting || !username || !password">
          {{ submitting ? '正在注册…' : '注 册' }}
        </button>
        <p class="field-hint" style="margin-top: 12px; text-align: center">
          已有账号？<span class="link" @click="goLogin">返回登录</span>
        </p>
      </form>
    </div>
  </div>
</template>

<script setup>
// 注册：开放注册固定考生身份（后端契约）。成功后回登录页。
import { computed, ref } from 'vue'
import { useTheme } from '../lib/theme'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { errMsg } from '../api'
import { toast } from '../components/ui'

const router = useRouter()

// 日/夜切换（SSOT §5 2026-09-09 整站覆盖）：无壳页右上角浮按钮
const { theme, toggle: toggleTheme } = useTheme()
const isDark = computed(() => theme.value === 'dark')
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const confirm = ref('')
const errorText = ref('')
const submitting = ref(false)

function goLogin() {
  router.push('/login')
}

async function onSubmit() {
  if (submitting.value) return
  if (password.value.length < 6) {
    errorText.value = '密码至少 6 位'
    return
  }
  if (password.value !== confirm.value) {
    errorText.value = '两次输入的密码不一致'
    return
  }
  submitting.value = true
  errorText.value = ''
  try {
    await auth.register(username.value.trim(), password.value)
    toast('注册成功，请登录')
    router.push('/login')
  } catch (e) {
    // 409 用户名已存在
    errorText.value = errMsg(e, '注册失败，请重试')
  } finally {
    submitting.value = false
  }
}
</script>
