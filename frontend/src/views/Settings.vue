<template>
  <div class="settings-page">
    <section class="settings-hero card radar-grid-bg">
      <div class="hero-copy">
        <div class="hero-kicker"><span class="signal-dot"></span> 控制台校准</div>
        <h1>{{ t('settings.title') }}</h1>
        <p class="muted">管理偏好、提醒通道、数据备份与系统状态，让续费雷达保持在可控参数内。</p>
      </div>
      <div class="hero-metrics">
        <div class="metric-card">
          <span>{{ t('settings.theme') }}</span>
          <b>{{ currentThemeLabel }}</b>
        </div>
        <div class="metric-card">
          <span>{{ t('settings.baseCurrency') }}</span>
          <b class="mono-data">{{ baseCurrency }}</b>
        </div>
        <div class="metric-card">
          <span>通知通道</span>
          <b class="mono-data">{{ enabledChannels }}/2</b>
        </div>
      </div>
    </section>

    <div class="grid two">
      <!-- 外观与偏好 -->
      <div class="card sect panel-card">
        <div class="panel-head">
          <div>
            <div class="panel-title"><span class="panel-signal"></span>{{ t('settings.theme') }}</div>
            <p class="muted">调整控制台外观与统计基准货币。</p>
          </div>
          <span class="tag mono-data">{{ baseCurrency }}</span>
        </div>
        <label>{{ t('settings.theme') }}</label>
        <div class="theme-picker">
          <button v-for="th in themes" :key="th.v" class="th" :class="{ on: theme === th.v }"
                  :style="{ background: th.c }" :title="t('settings.theme' + th.k)"
                  @click="theme = th.v; changeTheme()"></button>
        </div>
        <label>{{ t('settings.baseCurrency') }}</label>
        <select v-model="baseCurrency" @change="changeCurrency">
          <option v-for="c in currencies" :key="c.code" :value="c.code">{{ c.code }} {{ c.symbol }}</option>
        </select>
      </div>

      <!-- 账号与密码 -->
      <div class="card sect panel-card">
        <div class="panel-head">
          <div>
            <div class="panel-title"><span class="panel-signal"></span>{{ t('account.title') }}</div>
            <p class="muted">维护登录身份与访问凭据。</p>
          </div>
          <span class="tag">Profile</span>
        </div>
        <div class="form-grid">
          <div class="field">
            <label>{{ t('account.username') }}</label>
            <input v-model="acc.username" />
          </div>
          <div class="field">
            <label>{{ t('account.email') }}</label>
            <input v-model="acc.email" type="email" />
          </div>
        </div>
        <div class="actions-row">
          <button class="btn ghost sm" @click="saveAccount">{{ t('account.saveAccount') }}</button>
        </div>
        <hr />
        <div class="form-grid">
          <div class="field">
            <label>{{ t('account.oldPwd') }}</label>
            <input v-model="pwd.old_password" type="password" />
          </div>
          <div class="field">
            <label>{{ t('account.newPwd') }}</label>
            <input v-model="pwd.new_password" type="password" />
          </div>
        </div>
        <div class="actions-row">
          <button class="btn ghost sm" @click="changePwd">{{ t('account.changePwd') }}</button>
        </div>
        <p v-if="accMsg" class="feedback" :class="accOk ? 'ok' : 'err'">{{ accMsg }}</p>
      </div>
    </div>

    <!-- 常用货币当日汇率 -->
    <div class="card sect panel-card">
      <div class="panel-head">
        <div>
          <div class="panel-title"><span class="panel-signal"></span>{{ t('settings.rateTable') }}（{{ rates.base }}）</div>
          <p class="muted">
            {{ t('settings.rateTip', { base: rates.base }) }}
            <span v-if="rates.updated_at"> · {{ t('settings.updatedAt') }} {{ fmtTime(rates.updated_at) }}</span>
          </p>
        </div>
        <button class="btn ghost sm" @click="refreshRates">↻ {{ t('settings.refreshRates') }}</button>
      </div>
      <p v-if="rateMsg" class="feedback ok">{{ rateMsg }}</p>
      <div v-if="rates.items.length" class="rate-grid">
        <div v-for="r in rates.items" :key="r.code" class="rate">
          <div class="rate-code">{{ r.symbol }} {{ r.code }}</div>
          <div class="rate-val mono-data">1 = {{ r.per_unit_in_base }} <span class="muted">{{ rates.base }}</span></div>
        </div>
      </div>
      <p v-else class="muted empty-text">{{ t('settings.noRates') }}</p>
    </div>

    <!-- Telegram -->
    <div class="card sect panel-card channel-card">
      <div class="panel-head">
        <div>
          <div class="panel-title"><span class="panel-signal"></span>{{ t('settings.telegram') }}</div>
          <p class="muted">通过 Telegram Bot API 发送续费提醒，支持反代与 HTTP 代理。</p>
        </div>
        <label class="switch">
          <input type="checkbox" v-model="tg.enabled" @change="saveTg" />
          <span>{{ t('settings.tgEnabled') }}</span>
        </label>
      </div>
      <div class="hint-box">
        <span class="mono-data">01</span>
        <p>在 Telegram 找 @BotFather 创建机器人，拿到 Bot Token 填到下面。</p>
        <span class="mono-data">02</span>
        <p>给你的机器人发一条消息，点「{{ t('settings.getUpdates') }}」自动获取 Chat ID。</p>
      </div>
      <div class="form-grid wide">
        <div class="field span-2">
          <label>{{ t('settings.botToken') }}</label>
          <input v-model="tg.bot_token" placeholder="8954101204:AAGx00hzpMjR..." />
        </div>
        <div class="field">
          <label>{{ t('settings.chatId') }}</label>
          <input v-model="tg.chat_id" placeholder="123456789" />
        </div>
        <div class="field">
          <label>{{ t('settings.adminId') }}</label>
          <input v-model="tg.admin_id" placeholder="123456789" />
        </div>
        <div class="field">
          <label>{{ t('settings.apiBase') }}</label>
          <input v-model="tg.api_base" placeholder="https://api.telegram.org" />
        </div>
        <div class="field">
          <label>{{ t('settings.proxy') }}</label>
          <input v-model="tg.proxy" placeholder="http://127.0.0.1:7890" />
        </div>
      </div>
      <div class="actions-row wrap">
        <button class="btn" @click="saveTg">{{ t('settings.save') }}</button>
        <button class="btn ghost" @click="getUpdates">{{ t('settings.getUpdates') }}</button>
        <button class="btn ghost" @click="checkBot">{{ t('settings.checkBot') }}</button>
        <button class="btn ghost" @click="testSend">{{ t('settings.testSend') }}</button>
      </div>
      <p v-if="tgMsg" class="feedback" :class="tgOk ? 'ok' : 'err'">{{ tgMsg }}</p>
    </div>

    <!-- Bark -->
    <div class="card sect panel-card channel-card">
      <div class="panel-head">
        <div>
          <div class="panel-title"><span class="panel-signal"></span>{{ t('settings.bark') }}</div>
          <p class="muted">iOS 推送通道，可与 Telegram 同时启用并独立记录。</p>
        </div>
        <label class="switch">
          <input type="checkbox" v-model="bk.enabled" @change="saveBark" />
          <span>{{ t('settings.barkEnabled') }}</span>
        </label>
      </div>
      <p class="muted tip-text">{{ t('settings.barkTip') }}</p>
      <div class="form-grid wide">
        <div class="field span-2">
          <label>{{ t('settings.barkKey') }}</label>
          <input v-model="bk.device_key" placeholder="xxxxxxxxxxxxxxxxxxxxxx" />
        </div>
        <div class="field">
          <label>{{ t('settings.barkServer') }}</label>
          <input v-model="bk.server" placeholder="https://api.day.app" />
        </div>
        <div class="field">
          <label>{{ t('settings.barkSound') }}</label>
          <input v-model="bk.sound" placeholder="（可选）" />
        </div>
        <div class="field">
          <label>{{ t('settings.barkGroup') }}</label>
          <input v-model="bk.group" placeholder="Subly" />
        </div>
        <div class="field">
          <label>{{ t('settings.barkTtl') }}</label>
          <input v-model="bk.ttl" type="text" inputmode="numeric" pattern="\d*" :placeholder="t('settings.barkTtlPh')" />
        </div>
      </div>
      <div class="actions-row wrap">
        <button class="btn" @click="saveBark">{{ t('settings.save') }}</button>
        <button class="btn ghost" @click="testBark">{{ t('settings.testSend') }}</button>
      </div>
      <p v-if="bkMsg" class="feedback" :class="bkOk ? 'ok' : 'err'">{{ bkMsg }}</p>
    </div>

    <div class="grid two">
      <!-- 数据备份与恢复 -->
      <div class="card sect panel-card data-card">
        <div class="panel-head compact">
          <div>
            <div class="panel-title"><span class="panel-signal"></span>{{ t('backup.title') }}</div>
            <p class="muted">{{ t('backup.tip') }}</p>
          </div>
        </div>
        <div class="actions-row wrap">
          <button class="btn ghost" @click="exportData">⬇️ {{ t('backup.export') }}</button>
          <label class="btn ghost file-btn">⬆️ {{ t('backup.import') }}
            <input type="file" accept="application/json,.json" hidden @change="importData" />
          </label>
        </div>
        <label class="switch replace-switch"><input type="checkbox" v-model="importReplace" /> <span>{{ t('backup.replace') }}</span></label>
        <p v-if="backupMsg" class="feedback" :class="backupOk ? 'ok' : 'err'">{{ backupMsg }}</p>
      </div>

      <!-- 管理员：整站备份与恢复 -->
      <div class="card sect panel-card data-card admin-data" v-if="auth.user?.is_admin">
        <div class="panel-head compact">
          <div>
            <div class="panel-title"><span class="panel-signal warn"></span>{{ t('backupAll.title') }}</div>
            <p class="muted">{{ t('backupAll.tip') }}</p>
          </div>
        </div>
        <div class="actions-row wrap">
          <button class="btn ghost" @click="exportAll">⬇️ {{ t('backupAll.export') }}</button>
          <label class="btn ghost file-btn">⬆️ {{ t('backupAll.import') }}
            <input type="file" accept="application/json,.json" hidden @change="importAll" />
          </label>
        </div>
        <label class="switch replace-switch"><input type="checkbox" v-model="importAllReplace" /> <span>{{ t('backupAll.replace') }}</span></label>
        <p v-if="backupAllMsg" class="feedback" :class="backupAllOk ? 'ok' : 'err'">{{ backupAllMsg }}</p>
      </div>
    </div>

    <!-- 系统信息 -->
    <div class="card sect panel-card">
      <div class="panel-head">
        <div>
          <div class="panel-title"><span class="panel-signal"></span>{{ t('sys.title') }}</div>
          <p class="muted">当前实例、数据库与提醒扫描参数。</p>
        </div>
        <span v-if="sys?.db_configured" class="tag status-ok">{{ t('sys.configured') }}</span>
      </div>
      <div class="sys-grid" v-if="sys">
        <div class="si"><span class="muted">{{ t('sys.version') }}</span><b class="mono-data">{{ sys.version }}</b></div>
        <div class="si"><span class="muted">{{ t('sys.dbStatus') }}</span>
          <b class="ok" v-if="sys.db_configured">● {{ t('sys.configured') }}</b><b v-else>—</b></div>
        <div class="si"><span class="muted">{{ t('sys.serverTime') }}</span><b class="mono-data">{{ sys.server_time }}</b></div>
        <div class="si"><span class="muted">{{ t('sys.timezone') }}</span><b class="mono-data">{{ sys.timezone }}</b></div>
        <div class="si"><span class="muted">{{ t('sys.scanTime') }}</span><b class="mono-data">{{ sys.reminder_scan_time }}</b></div>
        <div class="si"><span class="muted">{{ t('sys.yourSubs') }}</span><b class="mono-data">{{ sys.your_subscriptions }}</b></div>
        <div class="si" v-if="sys.total_users != null"><span class="muted">{{ t('sys.totalUsers') }}</span><b class="mono-data">{{ sys.total_users }}</b></div>
        <div class="si" v-if="sys.total_subscriptions != null"><span class="muted">{{ t('sys.totalSubs') }}</span><b class="mono-data">{{ sys.total_subscriptions }}</b></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import { useAuth } from '../stores/auth'

const { t } = useI18n()
const auth = useAuth()

const themes = [
  { v: 'light', k: 'Light', c: '#ffffff' },
  { v: 'dark', k: 'Dark', c: '#181d2e' },
  { v: 'ocean', k: 'Ocean', c: '#06b6d4' },
  { v: 'forest', k: 'Forest', c: '#16a34a' },
  { v: 'purple', k: 'Purple', c: '#9333ea' }
]

const theme = ref(auth.user?.theme || 'light')
const baseCurrency = ref(auth.user?.base_currency || 'CNY')
const tg = reactive({
  enabled: auth.user?.telegram_enabled || false,
  bot_token: auth.user?.telegram_bot_token || '',
  chat_id: auth.user?.telegram_chat_id || '',
  admin_id: auth.user?.telegram_admin_id || '',
  api_base: auth.user?.telegram_api_base || '',
  proxy: auth.user?.telegram_proxy || ''
})
const bk = reactive({
  enabled: auth.user?.bark_enabled || false,
  device_key: auth.user?.bark_device_key || '',
  server: auth.user?.bark_server || '',
  sound: auth.user?.bark_sound || '',
  group: auth.user?.bark_group || '',
  ttl: auth.user?.bark_ttl ?? ''
})
const bkMsg = ref('')
const bkOk = ref(false)
const currencies = ref([])
const rateMsg = ref('')
const rates = ref({ base: baseCurrency.value, updated_at: null, items: [] })
const tgMsg = ref('')
const tgOk = ref(false)

const acc = reactive({ username: auth.user?.username || '', email: auth.user?.email || '' })
const pwd = reactive({ old_password: '', new_password: '' })
const accMsg = ref('')
const accOk = ref(false)
const sys = ref(null)

const backupMsg = ref('')
const backupOk = ref(false)
const importReplace = ref(false)

const backupAllMsg = ref('')
const backupAllOk = ref(false)
const importAllReplace = ref(false)

const currentThemeLabel = computed(() => {
  const item = themes.find((x) => x.v === theme.value)
  return item ? t('settings.theme' + item.k) : theme.value
})
const enabledChannels = computed(() => Number(Boolean(tg.enabled)) + Number(Boolean(bk.enabled)))

async function exportData() {
  backupMsg.value = ''
  try {
    const { data } = await api.get('/api/backup/export')
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const stamp = new Date().toISOString().slice(0, 10)
    a.href = url
    a.download = `subly-backup-${stamp}.json`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    backupOk.value = true
    backupMsg.value = t('backup.exportOk')
  } catch (e) {
    backupOk.value = false
    backupMsg.value = e.response?.data?.detail || 'Error'
  }
}

async function importData(e) {
  const file = e.target.files[0]
  if (!file) return
  backupMsg.value = ''
  if (importReplace.value && !window.confirm(t('backup.replaceConfirm'))) {
    e.target.value = ''
    return
  }
  try {
    const json = JSON.parse(await file.text())
    const { data } = await api.post('/api/backup/import', { data: json, replace: importReplace.value })
    backupOk.value = true
    backupMsg.value = t('backup.importOk', { n: data.imported })
  } catch (err) {
    backupOk.value = false
    backupMsg.value = err.response?.data?.detail || t('backup.importFail')
  } finally {
    e.target.value = ''
  }
}

async function exportAll() {
  backupAllMsg.value = ''
  try {
    const { data } = await api.get('/api/backup/export-all')
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const stamp = new Date().toISOString().slice(0, 10)
    a.href = url
    a.download = `subly-full-backup-${stamp}.json`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    backupAllOk.value = true
    backupAllMsg.value = t('backupAll.exportOk', { n: data.users?.length || 0 })
  } catch (e) {
    backupAllOk.value = false
    backupAllMsg.value = e.response?.data?.detail || 'Error'
  }
}

async function importAll(e) {
  const file = e.target.files[0]
  if (!file) return
  backupAllMsg.value = ''
  if (!window.confirm(t(importAllReplace.value ? 'backupAll.replaceConfirm' : 'backupAll.importConfirm'))) {
    e.target.value = ''
    return
  }
  try {
    const json = JSON.parse(await file.text())
    const { data } = await api.post('/api/backup/import-all', { data: json, replace: importAllReplace.value })
    backupAllOk.value = true
    backupAllMsg.value = t('backupAll.importOk', { users: data.users, created: data.created_users, n: data.imported })
  } catch (err) {
    backupAllOk.value = false
    backupAllMsg.value = err.response?.data?.detail || t('backup.importFail')
  } finally {
    e.target.value = ''
  }
}

async function saveAccount() {
  accMsg.value = ''
  try {
    await api.patch('/api/me/account', { username: acc.username, email: acc.email })
    await auth.fetchMe()
    accOk.value = true; accMsg.value = t('account.accountOk')
  } catch (e) { accOk.value = false; accMsg.value = e.response?.data?.detail || 'Error' }
}
async function changePwd() {
  accMsg.value = ''
  try {
    await api.post('/api/me/password', pwd)
    pwd.old_password = ''; pwd.new_password = ''
    accOk.value = true; accMsg.value = t('account.pwdOk')
  } catch (e) { accOk.value = false; accMsg.value = e.response?.data?.detail || 'Error' }
}

async function changeTheme() { await auth.updateMe({ theme: theme.value }) }
async function changeCurrency() {
  await auth.updateMe({ base_currency: baseCurrency.value })
  loadRates()
}

function fmtTime(s) { return s ? new Date(s).toLocaleString() : '' }
async function loadRates() {
  try { rates.value = (await api.get('/api/currencies/rate-table')).data }
  catch { /* ignore */ }
}
async function saveTg() {
  await auth.updateMe({
    telegram_enabled: tg.enabled,
    telegram_bot_token: tg.bot_token,
    telegram_chat_id: tg.chat_id,
    telegram_admin_id: tg.admin_id,
    telegram_api_base: tg.api_base || null,
    telegram_proxy: tg.proxy || null
  })
  tgOk.value = true; tgMsg.value = t('settings.saved')
}

function normalizeBarkTtl() {
  const raw = bk.ttl
  if (raw === '' || raw === null || raw === undefined) return null
  const text = String(raw).trim()
  if (!text) return null
  if (!/^\d+$/.test(text)) {
    bkOk.value = false
    bkMsg.value = t('settings.barkTtlInvalid')
    return undefined
  }
  return Number(text)
}

async function saveBark() {
  const ttl = normalizeBarkTtl()
  if (ttl === undefined) return false
  await auth.updateMe({
    bark_enabled: bk.enabled,
    bark_device_key: bk.device_key,
    bark_server: bk.server || null,
    bark_sound: bk.sound || null,
    bark_group: bk.group || null,
    bark_ttl: ttl
  })
  bkOk.value = true; bkMsg.value = t('settings.saved')
  return true
}

async function testBark() {
  const saved = await saveBark()
  if (!saved) return
  const ttl = normalizeBarkTtl()
  try {
    await api.post('/api/notifications/bark/test', { device_key: bk.device_key, server: bk.server || null, ttl })
    bkOk.value = true; bkMsg.value = t('settings.testOk')
  } catch (e) { bkOk.value = false; bkMsg.value = e.response?.data?.detail || 'Error' }
}

async function refreshRates() {
  try {
    await api.post('/api/currencies/rates/refresh')
    rateMsg.value = t('settings.ratesUpdated')
    await loadRates()
  } catch (e) { rateMsg.value = e.response?.data?.detail || 'Error' }
}
async function checkBot() {
  await saveTg()
  try {
    const { data } = await api.get('/api/notifications/telegram/me')
    tgOk.value = true; tgMsg.value = `${t('settings.botOk')}: @${data.result?.username}`
  } catch (e) { tgOk.value = false; tgMsg.value = t('settings.botFail') + ': ' + (e.response?.data?.detail || '') }
}
async function testSend() {
  await saveTg()
  try {
    await api.post('/api/notifications/telegram/test', { chat_id: tg.chat_id })
    tgOk.value = true; tgMsg.value = t('settings.testOk')
  } catch (e) { tgOk.value = false; tgMsg.value = e.response?.data?.detail || 'Error' }
}
async function getUpdates() {
  await saveTg()
  try {
    const { data } = await api.get('/api/notifications/telegram/updates')
    const ids = (data.result || []).map((u) => u.message?.chat?.id).filter(Boolean)
    tgOk.value = true
    tgMsg.value = ids.length ? 'Chat IDs: ' + [...new Set(ids)].join(', ') : 'No messages yet'
    if (ids.length) tg.chat_id = String(ids[ids.length - 1])
  } catch (e) { tgOk.value = false; tgMsg.value = e.response?.data?.detail || 'Error' }
}

onMounted(async () => {
  currencies.value = (await api.get('/api/currencies')).data
  sys.value = (await api.get('/api/system/info')).data
  loadRates()
})
</script>

<style scoped>
.settings-page { display: flex; flex-direction: column; gap: 16px; }
.settings-hero { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 24px; align-items: end;
  padding: 24px; background: linear-gradient(135deg, color-mix(in srgb, var(--surface) 88%, var(--radar-panel)), var(--surface)); }
.settings-hero > * { position: relative; z-index: 1; }
.hero-kicker { display: flex; align-items: center; gap: 8px; color: var(--text-soft); font-size: 12px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
h1 { margin: 8px 0 8px; }
.hero-copy p { margin: 0; max-width: 640px; line-height: 1.7; }
.hero-metrics { display: grid; grid-template-columns: repeat(3, minmax(96px, 1fr)); gap: 10px; min-width: 360px; }
.metric-card { padding: 12px; border-radius: 14px; border: 1px solid color-mix(in srgb, var(--signal-cyan) 22%, var(--border));
  background: color-mix(in srgb, var(--surface-2) 78%, transparent); }
.metric-card span { display: block; color: var(--text-soft); font-size: 12px; margin-bottom: 5px; }
.metric-card b { font-size: 16px; }
.two { grid-template-columns: 1fr 1fr; }
.sect { margin: 0; }
.panel-card { position: relative; overflow: hidden; }
.panel-card::after { content: ''; position: absolute; inset: auto 18px 0; height: 1px;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--signal-cyan) 32%, transparent), transparent); pointer-events: none; }
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }
.panel-head.compact { margin-bottom: 12px; }
.panel-head p { margin: 5px 0 0; font-size: 13px; line-height: 1.6; max-width: 760px; }
.panel-title { display: flex; align-items: center; gap: 9px; font-size: 16px; font-weight: 850; letter-spacing: -.02em; }
.panel-signal { width: 9px; height: 9px; border-radius: 999px; background: var(--signal-cyan);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--signal-cyan) 13%, transparent), 0 0 18px color-mix(in srgb, var(--signal-cyan) 45%, transparent); }
.panel-signal.warn { background: var(--warning); box-shadow: 0 0 0 4px color-mix(in srgb, var(--warning) 15%, transparent), 0 0 18px color-mix(in srgb, var(--warning) 38%, transparent); }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 12px; }
.form-grid.wide { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.field.span-2 { grid-column: span 2; }
hr { border: none; border-top: 1px solid var(--border); margin: 16px 0; }
.feedback { margin: 10px 0 0; font-size: 13px; line-height: 1.5; }
.ok { color: var(--success); }
.err { color: var(--danger); word-break: break-all; }
.actions-row { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
.actions-row.wrap { flex-wrap: wrap; }
.switch { display: inline-flex; align-items: center; gap: 7px; min-height: 38px; font-size: 13px; color: var(--text-soft); cursor: pointer; width: auto; margin: 0; }
.switch input { width: auto; }
.replace-switch { margin-top: 12px; align-items: flex-start; }
.theme-picker { display: flex; gap: 10px; margin: 6px 0 8px; }
.th { width: 40px; height: 40px; border-radius: 50%; border: 2px solid var(--border); cursor: pointer; padding: 0; }
.th.on { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft); }
.rate-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; }
.rate { border: 1px solid var(--border); border-radius: 12px; padding: 11px 12px; background: var(--surface-2);
  transition: transform .15s ease, border-color .15s ease; }
.rate:hover { transform: translateY(-2px); border-color: var(--primary); }
.rate-code { font-weight: 750; font-size: 14px; }
.rate-val { font-size: 13px; color: var(--text); margin-top: 4px; }
.hint-box { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px 10px; padding: 12px;
  border: 1px solid var(--border); border-radius: 13px; background: color-mix(in srgb, var(--surface-2) 82%, transparent); margin-bottom: 12px; }
.hint-box span { color: var(--signal-cyan); font-size: 12px; }
.hint-box p { margin: 0; color: var(--text-soft); font-size: 13px; line-height: 1.5; }
.tip-text { margin-top: 0; font-size: 13px; line-height: 1.6; }
.file-btn { width: auto; margin: 0; }
.data-card { min-height: 100%; }
.admin-data { border-color: color-mix(in srgb, var(--warning) 35%, var(--border)); }
.status-ok { background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success); }
.sys-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
.si { display: flex; flex-direction: column; gap: 5px; padding: 13px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 12px; font-size: 14px; }
.si .muted { font-size: 12px; }
.empty-text { margin-bottom: 0; }
@media (max-width: 920px) {
  .settings-hero { grid-template-columns: 1fr; }
  .hero-metrics { min-width: 0; }
  .two { grid-template-columns: 1fr; }
  .form-grid.wide { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 720px) {
  .settings-page { gap: 14px; }
  .settings-hero { padding: 18px; }
  .hero-metrics { grid-template-columns: 1fr; }
  .form-grid, .form-grid.wide { grid-template-columns: 1fr; }
  .field.span-2 { grid-column: auto; }
  .panel-head { align-items: stretch; }
  .panel-head .btn, .actions-row .btn, .actions-row .file-btn { flex: 1 1 100%; justify-content: center; text-align: center; }
  .actions-row { align-items: stretch; }
}
</style>
