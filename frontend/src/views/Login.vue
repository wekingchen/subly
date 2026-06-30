<template>
  <div class="auth-wrap">
    <section class="radar-panel radar-grid-bg">
      <div class="rp-kicker"><span class="signal-dot"></span>{{ t('auth.radarKicker') }}</div>
      <h1>{{ t('auth.radarTitle') }}</h1>
      <p>{{ t('auth.radarSubtitle') }}</p>
      <div class="radar-orbit" aria-hidden="true">
        <span class="orbit o1"></span>
        <span class="orbit o2"></span>
        <span class="orbit o3"></span>
        <span class="sweep"></span>
        <span class="ping p1"></span>
        <span class="ping p2"></span>
        <span class="ping p3"></span>
      </div>
      <div class="rp-signals">
        <div><b class="mono-data">30D</b><span>{{ t('auth.radarScan') }}</span></div>
        <div><b class="mono-data">TG+Bark</b><span>{{ t('auth.radarAlerts') }}</span></div>
        <div><b class="mono-data">SQLite</b><span>{{ t('auth.radarLedger') }}</span></div>
      </div>
    </section>

    <div class="card auth-card">
      <div class="logo"><span class="brand-mark">⌁</span></div>
      <h2>Subly</h2>
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
.auth-wrap { min-height: 100vh; display: flex; align-items: stretch; justify-content: center; padding: 0; }
/* 左侧雷达面板 */
.radar-panel { flex: 1.05; min-width: 0; padding: 56px 56px 40px; position: relative; display: flex; flex-direction: column;
  gap: 14px; background: linear-gradient(160deg, var(--radar-bg), #11182b 70%); color: var(--ledger-ink); overflow: hidden; }
.rp-kicker { display: inline-flex; align-items: center; gap: 9px; font-size: 11px; text-transform: uppercase; letter-spacing: .22em; color: var(--signal-cyan); }
.radar-panel h1 { font-size: 40px; line-height: 1.04; letter-spacing: -.03em; margin: 6px 0 0; max-width: 16ch; }
.radar-panel p { color: var(--ledger-muted); max-width: 38ch; margin: 0; line-height: 1.65; }
.radar-orbit { position: relative; width: 300px; height: 300px; margin: 30px auto 8px; }
.radar-orbit .orbit { position: absolute; inset: 0; margin: auto; border: 1px solid color-mix(in srgb, var(--signal-cyan) 26%, transparent); border-radius: 50%; }
.radar-orbit .o1 { width: 300px; height: 300px; }
.radar-orbit .o2 { width: 210px; height: 210px; border-color: color-mix(in srgb, var(--signal-cyan) 20%, transparent); }
.radar-orbit .o3 { width: 120px; height: 120px; border-color: color-mix(in srgb, var(--signal-cyan) 16%, transparent); }
.radar-orbit .sweep { position: absolute; inset: 0; margin: auto; width: 150px; height: 150px; border-radius: 50%;
  background: conic-gradient(from 0deg, color-mix(in srgb, var(--signal-cyan) 42%, transparent), transparent 70%); opacity: .55; animation: radar-sweep 5s linear infinite; }
@keyframes radar-sweep { to { transform: rotate(360deg); } }
.radar-orbit .ping { position: absolute; border-radius: 50%; background: var(--signal-cyan); box-shadow: 0 0 14px var(--signal-cyan); }
.radar-orbit .p1 { width: 8px; height: 8px; top: 22%; left: 64%; }
.radar-orbit .p2 { width: 6px; height: 6px; top: 62%; left: 38%; background: var(--renewal-amber); box-shadow: 0 0 14px var(--renewal-amber); }
.radar-orbit .p3 { width: 5px; height: 5px; top: 44%; left: 78%; background: var(--overdue-red); box-shadow: 0 0 14px var(--overdue-red); }
.rp-signals { display: flex; flex-wrap: wrap; gap: 18px; margin-top: auto; padding-top: 18px; border-top: 1px solid color-mix(in srgb, var(--signal-cyan) 16%, transparent); }
.rp-signals > div { display: flex; flex-direction: column; gap: 3px; min-width: 96px; }
.rp-signals b { color: var(--signal-cyan); font-size: 16px; }
.rp-signals span { color: var(--ledger-muted); font-size: 12px; }
/* 右侧登录卡片 */
.auth-card { width: 420px; max-width: 92vw; text-align: center; align-self: center; margin: 24px; }
.logo { margin-bottom: 4px; }
.brand-mark { display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 44px; border-radius: 13px;
  background: linear-gradient(135deg, var(--signal-cyan), var(--primary)); color: #06101f; font-weight: 900; font-size: 22px;
  box-shadow: 0 0 26px color-mix(in srgb, var(--signal-cyan) 42%, transparent); }
h2 { margin: 8px 0 4px; font-weight: 800; letter-spacing: -.03em; }
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

@media (max-width: 880px) {
  .auth-wrap { flex-direction: column; padding: 16px; }
  .radar-panel { padding: 26px 22px 18px; }
  .radar-panel h1 { font-size: 26px; }
  .radar-orbit { width: 180px; height: 180px; margin: 6px auto 0; }
  .radar-orbit .o1 { width: 180px; height: 180px; }
  .radar-orbit .o2 { width: 126px; height: 126px; }
  .radar-orbit .o3 { width: 72px; height: 72px; }
  .radar-orbit .sweep { width: 90px; height: 90px; }
  .rp-signals { margin-top: 14px; gap: 14px; }
  .auth-card { margin: 18px auto 0; }
}
@media (prefers-reduced-motion: reduce) {
  .radar-orbit .sweep { animation: none; }
}
</style>

