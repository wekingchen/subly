<template>
  <div class="auth-wrap">
    <div class="card auth-card">
      <div class="logo">🔔</div>
      <h2>{{ t('app.title') }}</h2>
      <p class="tag muted">{{ t('app.tagline') }}</p>

      <!-- 登录 / 注册 -->
      <template v-if="step === 'form'">
        <div class="seg">
          <button :class="{ on: mode === 'login' }" @click="mode = 'login'">{{ t('auth.login') }}</button>
          <button :class="{ on: mode === 'register' }" @click="mode = 'register'">{{ t('auth.register') }}</button>
        </div>

        <label>{{ t('auth.username') }}</label>
        <input v-model="username" @keyup.enter="submit" />

        <template v-if="mode === 'register'">
          <label>{{ t('auth.email') }}</label>
          <input v-model="email" type="email" />
        </template>

        <label>{{ t('auth.password') }}</label>
        <input v-model="password" type="password" @keyup.enter="submit" />

        <p v-if="error" class="err">{{ error }}</p>
        <p v-if="info" class="ok">{{ info }}</p>
        <button class="btn" style="width:100%;margin-top:16px" :disabled="busy" @click="submit">
          {{ mode === 'login' ? t('auth.loginBtn') : t('auth.registerBtn') }}
        </button>
      </template>

      <!-- 邮箱验证码 -->
      <template v-else-if="step === 'verify'">
        <h3 class="step-t">📧 {{ t('auth.verifyTitle') }}</h3>
        <p class="muted hint">{{ t('auth.verifyTip', { email }) }}</p>
        <label>{{ t('auth.code') }}</label>
        <input v-model="code" :placeholder="t('auth.codePh')" maxlength="6" @keyup.enter="doVerify" />
        <p v-if="error" class="err">{{ error }}</p>
        <button class="btn" style="width:100%;margin-top:16px" :disabled="busy" @click="doVerify">
          {{ t('auth.verifyBtn') }}
        </button>
        <a href="#" class="back" @click.prevent="backToLogin">{{ t('auth.backToLogin') }}</a>
      </template>

      <!-- 等待审核 -->
      <template v-else-if="step === 'pending'">
        <h3 class="step-t">⏳ {{ t('auth.pendingTitle') }}</h3>
        <p class="muted hint">{{ info || t('auth.pendingMsg') }}</p>
        <button class="btn" style="width:100%;margin-top:16px" @click="backToLogin">
          {{ t('auth.backToLogin') }}
        </button>
      </template>

      <div class="lang">
        <a href="#" @click.prevent="setLang('zh')">中文</a>
        <a href="#" @click.prevent="setLang('en')">EN</a>
        <a href="#" @click.prevent="setLang('ru')">RU</a>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useAuth } from '../stores/auth'

const { t, locale } = useI18n()
const router = useRouter()
const auth = useAuth()

const step = ref('form')      // form | verify | pending
const mode = ref('login')
const username = ref('')
const email = ref('')
const password = ref('')
const code = ref('')
const error = ref('')
const info = ref('')
const busy = ref(false)

function setLang(l) {
  locale.value = l
  localStorage.setItem('locale', l)
}

function backToLogin() {
  step.value = 'form'; mode.value = 'login'
  error.value = ''; code.value = ''
}

async function submit() {
  error.value = ''; info.value = ''
  busy.value = true
  try {
    if (mode.value === 'login') {
      await auth.login(username.value, password.value)
      router.push('/dashboard')
    } else {
      const res = await auth.register(username.value, email.value, password.value)
      if (res.status === 'verify') { step.value = 'verify' }
      else if (res.status === 'pending') { step.value = 'pending'; info.value = res.message }
      else {
        // 无需验证/审核：直接登录
        try {
          await auth.login(username.value, password.value)
          router.push('/dashboard')
        } catch {
          mode.value = 'login'; info.value = t('auth.registerOk')
        }
      }
    }
  } catch (e) {
    error.value = e.response?.data?.detail || t('auth.loginFail')
  } finally {
    busy.value = false
  }
}

async function doVerify() {
  error.value = ''
  busy.value = true
  try {
    const res = await auth.verifyEmail(email.value, code.value)
    if (res.status === 'pending') { step.value = 'pending'; info.value = res.message }
    else {
      try {
        await auth.login(username.value, password.value)
        router.push('/dashboard')
      } catch {
        step.value = 'form'; mode.value = 'login'; info.value = t('auth.registerOk')
      }
    }
  } catch (e) {
    error.value = e.response?.data?.detail || 'Error'
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.auth-wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px;
  background: radial-gradient(1200px 600px at 50% -10%, var(--primary-soft), transparent 60%); }
.auth-card { width: 380px; max-width: 92vw; text-align: center; }
.logo { font-size: 40px; }
h2 { margin: 8px 0 4px; }
.tag { font-size: 13px; margin: 0 0 14px; }
.step-t { margin: 8px 0 6px; }
.hint { font-size: 13px; line-height: 1.6; }
.seg { display: flex; background: var(--bg); border: none; border-radius: 8px; padding: 4px; margin-bottom: 8px; }
.seg button { flex: 1; border: none; background: transparent; min-height: 44px; padding: 8px; border-radius: 6px;
  cursor: pointer; color: var(--text-soft); }
.seg button.on { background: var(--surface); color: var(--text); box-shadow: var(--shadow); }
label { text-align: left; }
.err { color: var(--danger); font-size: 13px; margin-top: 10px; }
.ok { color: var(--success); font-size: 13px; margin-top: 10px; }
.back { display: block; margin-top: 14px; font-size: 13px; }
.lang { display: flex; justify-content: center; gap: 6px; align-items: center; margin-top: 16px; font-size: 13px; color: var(--text-soft); }
.lang a { display: inline-flex; align-items: center; min-height: 44px; padding: 0 8px; }
</style>
