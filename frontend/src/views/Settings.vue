<template>
  <div class="settings-page">
    <section class="settings-hero card radar-grid-bg">
      <div class="hero-copy">
        <div class="hero-kicker"><span class="signal-dot"></span> 控制台校准</div>
        <h1 tabindex="-1">{{ t('settings.title') }}</h1>
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
          <b class="mono-data">{{ enabledChannels }}/3</b>
        </div>
      </div>
    </section>

    <nav class="settings-nav" :aria-label="t('settings.sectionNav')">
      <RouterLink
        v-for="item in settingsNavItems"
        :key="item.id"
        class="settings-nav-link"
        :to="{ path: '/settings', hash: `#${item.id}` }"
        :aria-current="activeSection === item.id ? 'location' : undefined"
      >
        {{ t(item.label) }}
      </RouterLink>
    </nav>

    <div class="grid two">
      <!-- 外观与偏好 -->
      <div id="preferences" class="card sect panel-card settings-anchor">
        <div class="panel-head">
          <div>
            <div class="panel-title"><span class="panel-signal"></span>{{ t('settings.theme') }}</div>
            <p class="muted">调整控制台外观与统计基准货币。</p>
          </div>
          <span class="tag mono-data">{{ baseCurrency }}</span>
        </div>
        <fieldset class="theme-fieldset">
          <legend>{{ t('settings.theme') }}</legend>
          <div class="theme-picker">
            <button v-for="th in themes" :key="th.v" type="button" class="th" :class="{ on: theme === th.v }"
                    :style="{ background: th.c }" :title="t('settings.theme' + th.k)"
                    :aria-label="t('settings.theme' + th.k)" :aria-pressed="theme === th.v"
                    :disabled="themeSaving" @click="changeTheme(th.v)"></button>
          </div>
        </fieldset>
        <label for="settings-base-currency">{{ t('settings.baseCurrency') }}</label>
        <select id="settings-base-currency" v-model="baseCurrency" name="base_currency" autocomplete="off"
                :disabled="currencySaving" @change="changeCurrency">
          <option
            v-for="c in currencies"
            :key="c.code"
            :value="c.code"
            :disabled="c.is_custom && c.rate_to_user_base == null && c.code !== auth.user?.base_currency"
          >{{ c.code }} {{ c.symbol }}</option>
        </select>
        <form @submit.prevent="saveBudget">
          <label for="settings-monthly-budget">{{ t('settings.monthlyBudget') }} <span class="muted mono-data">({{ baseCurrency }})</span></label>
          <div class="budget-row">
            <input id="settings-monthly-budget" v-model="monthlyBudget" name="monthly_budget" type="number"
                   min="0" step="0.01" inputmode="decimal" autocomplete="off" :placeholder="t('settings.budgetPh')"
                   :disabled="budgetSaving" />
            <button class="btn ghost sm" type="submit" :disabled="budgetSaving">{{ t('settings.save') }}</button>
          </div>
        </form>
        <p class="muted budget-hint">{{ t('settings.budgetHint') }}</p>
        <p v-if="prefMsg" class="feedback" :class="prefOk ? 'ok' : 'err'" :role="prefOk ? 'status' : 'alert'">{{ prefMsg }}</p>
      </div>

      <!-- 账号与密码 -->
      <div id="account" class="card sect panel-card settings-anchor">
        <div class="panel-head">
          <div>
            <div class="panel-title"><span class="panel-signal"></span>{{ t('account.title') }}</div>
            <p class="muted">维护登录身份与访问凭据。</p>
          </div>
          <span class="tag">Profile</span>
        </div>
        <form @submit.prevent="saveAccount">
          <div class="form-grid">
            <div class="field">
              <label for="account-username">{{ t('account.username') }}</label>
              <input id="account-username" v-model="acc.username" name="username" autocomplete="username" :disabled="accountSaving" />
            </div>
            <div class="field">
              <label for="account-email">{{ t('account.email') }}</label>
              <input id="account-email" v-model="acc.email" name="email" type="email" autocomplete="email" :disabled="accountSaving" />
            </div>
          </div>
          <div class="actions-row">
            <button class="btn ghost sm" type="submit" :disabled="accountSaving">{{ t('account.saveAccount') }}</button>
          </div>
        </form>
        <hr />
        <form @submit.prevent="changePwd">
          <div class="form-grid">
            <div class="field">
              <label for="account-current-password">{{ t('account.oldPwd') }}</label>
              <input id="account-current-password" v-model="pwd.old_password" name="current_password" type="password"
                     autocomplete="current-password" :disabled="passwordSaving" />
            </div>
            <div class="field">
              <label for="account-new-password">{{ t('account.newPwd') }}</label>
              <input id="account-new-password" v-model="pwd.new_password" name="new_password" type="password"
                     autocomplete="new-password" :disabled="passwordSaving" />
            </div>
          </div>
          <div class="actions-row">
            <button class="btn ghost sm" type="submit" :disabled="passwordSaving">{{ t('account.changePwd') }}</button>
          </div>
        </form>
        <p v-if="accMsg" class="feedback" :class="accOk ? 'ok' : 'err'" :role="accOk ? 'status' : 'alert'">{{ accMsg }}</p>
      </div>
    </div>

    <section id="rates-and-reference-data" class="settings-group settings-anchor">
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
        <button class="btn ghost sm" type="button" :disabled="ratesRefreshing" @click="refreshRates">↻ {{ t('settings.refreshRates') }}</button>
      </div>
      <p v-if="rateMsg" class="feedback" :class="rateOk ? 'ok' : 'err'" :role="rateOk ? 'status' : 'alert'">{{ rateMsg }}</p>
      <div v-if="rates.items.length" class="rate-grid">
        <div v-for="r in rates.items" :key="r.code" class="rate">
          <div class="rate-code">{{ r.symbol }} {{ r.code }}</div>
          <div class="rate-val mono-data">1 = {{ r.per_unit_in_base }} <span class="muted">{{ rates.base }}</span></div>
        </div>
      </div>
      <p v-else class="muted empty-text">{{ t('settings.noRates') }}</p>
    </div>

    <!-- 订阅参考数据 -->
    <section class="reference-section" aria-labelledby="reference-data-title">
      <div class="section-intro">
        <h2 id="reference-data-title">{{ t('settings.referenceDataTitle') }}</h2>
        <p class="muted">{{ t('settings.referenceDataTip') }}</p>
      </div>
      <div class="grid two reference-grid">
        <CategoryManager />
        <PaymentMethodManager />
      </div>
      <CurrencyManager :base-currency="auth.user?.base_currency || baseCurrency" @changed="handleCurrencyChanged" />
    </section>
    </section>

    <section id="calendar-feed" class="settings-anchor">
      <CalendarFeedManager />
    </section>

    <section id="notifications" class="settings-group settings-anchor" aria-labelledby="notifications-title">
      <div class="section-intro">
        <h2 id="notifications-title">{{ t('settings.notificationsSection') }}</h2>
        <p class="muted">{{ t('settings.notificationsSectionTip') }}</p>
      </div>

    <!-- Telegram -->
    <form class="card sect panel-card channel-card" @submit.prevent="saveTg">
      <div class="panel-head">
        <div>
          <div class="panel-title"><span class="panel-signal"></span>{{ t('settings.telegram') }}</div>
          <p class="muted">通过 Telegram Bot API 发送续费提醒，支持反代与 HTTP 代理。</p>
        </div>
        <label class="switch" for="telegram-enabled">
          <input id="telegram-enabled" v-model="tg.enabled" name="telegram_enabled" type="checkbox"
                 :disabled="tgBusy" @change="saveTg" />
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
          <label for="telegram-bot-token">{{ t('settings.botToken') }}</label>
          <input id="telegram-bot-token" v-model="tg.bot_token" name="telegram_bot_token" autocomplete="off"
                 placeholder="8954101204:AAGx00hzpMjR..." :disabled="tgBusy" />
        </div>
        <div class="field">
          <label for="telegram-chat-id">{{ t('settings.chatId') }}</label>
          <input id="telegram-chat-id" v-model="tg.chat_id" name="telegram_chat_id" autocomplete="off"
                 placeholder="123456789" :disabled="tgBusy" />
        </div>
        <div class="field">
          <label for="telegram-admin-id">{{ t('settings.adminId') }}</label>
          <input id="telegram-admin-id" v-model="tg.admin_id" name="telegram_admin_id" autocomplete="off"
                 placeholder="123456789" :disabled="tgBusy" />
        </div>
        <div class="field">
          <label for="telegram-api-base">{{ t('settings.apiBase') }}</label>
          <input id="telegram-api-base" v-model="tg.api_base" name="telegram_api_base" type="url" autocomplete="url"
                 placeholder="https://api.telegram.org" :disabled="tgBusy" />
        </div>
        <div class="field">
          <label for="telegram-proxy">{{ t('settings.proxy') }}</label>
          <input id="telegram-proxy" v-model="tg.proxy" name="telegram_proxy" autocomplete="off"
                 placeholder="http://127.0.0.1:7890" :disabled="tgBusy" />
        </div>
      </div>
      <div class="actions-row wrap">
        <button class="btn" type="submit" :disabled="tgBusy">{{ t('settings.save') }}</button>
        <button class="btn ghost" type="button" :disabled="tgBusy" @click="getUpdates">{{ t('settings.getUpdates') }}</button>
        <button class="btn ghost" type="button" :disabled="tgBusy" @click="checkBot">{{ t('settings.checkBot') }}</button>
        <button class="btn ghost" type="button" :disabled="tgBusy" @click="testSend">{{ t('settings.testSend') }}</button>
      </div>
      <p v-if="tgMsg" class="feedback" :class="tgOk ? 'ok' : 'err'" :role="tgOk ? 'status' : 'alert'">{{ tgMsg }}</p>
    </form>

    <!-- Bark -->
    <form class="card sect panel-card channel-card" @submit.prevent="saveBark">
      <div class="panel-head">
        <div>
          <div class="panel-title"><span class="panel-signal"></span>{{ t('settings.bark') }}</div>
          <p class="muted">iOS 推送通道，可与 Telegram 同时启用并独立记录。</p>
        </div>
        <label class="switch" for="bark-enabled">
          <input id="bark-enabled" v-model="bk.enabled" name="bark_enabled" type="checkbox"
                 :disabled="barkBusy" @change="saveBark" />
          <span>{{ t('settings.barkEnabled') }}</span>
        </label>
      </div>
      <p class="muted tip-text">{{ t('settings.barkTip') }}</p>
      <div class="form-grid wide">
        <div class="field span-2">
          <label for="bark-device-key">{{ t('settings.barkKey') }}</label>
          <input id="bark-device-key" v-model="bk.device_key" name="bark_device_key" autocomplete="off"
                 placeholder="xxxxxxxxxxxxxxxxxxxxxx" :disabled="barkBusy" />
        </div>
        <div class="field">
          <label for="bark-server">{{ t('settings.barkServer') }}</label>
          <input id="bark-server" v-model="bk.server" name="bark_server" type="url" autocomplete="url"
                 placeholder="https://api.day.app" :disabled="barkBusy" />
        </div>
        <div class="field">
          <label for="bark-sound">{{ t('settings.barkSound') }}</label>
          <input id="bark-sound" v-model="bk.sound" name="bark_sound" autocomplete="off"
                 placeholder="（可选）" :disabled="barkBusy" />
        </div>
        <div class="field">
          <label for="bark-group">{{ t('settings.barkGroup') }}</label>
          <input id="bark-group" v-model="bk.group" name="bark_group" autocomplete="off"
                 placeholder="Subly" :disabled="barkBusy" />
        </div>
        <div class="field">
          <label for="bark-ttl">{{ t('settings.barkTtl') }}</label>
          <input id="bark-ttl" v-model="bk.ttl" name="bark_ttl" type="text" inputmode="numeric" pattern="\d*"
                 autocomplete="off" :placeholder="t('settings.barkTtlPh')" :disabled="barkBusy" />
        </div>
      </div>
      <div class="actions-row wrap">
        <button class="btn" type="submit" :disabled="barkBusy">{{ t('settings.save') }}</button>
        <button class="btn ghost" type="button" :disabled="barkBusy" @click="testBark">{{ t('settings.testSend') }}</button>
      </div>
      <p v-if="bkMsg" class="feedback" :class="bkOk ? 'ok' : 'err'" :role="bkOk ? 'status' : 'alert'">{{ bkMsg }}</p>
    </form>

    <!-- Webhook -->
    <form class="card sect panel-card channel-card" @submit.prevent="saveWebhook">
      <div class="panel-head">
        <div>
          <div class="panel-title"><span class="panel-signal"></span>{{ t('settings.webhook') }}</div>
          <p class="muted">{{ t('settings.webhookTip') }}</p>
        </div>
        <label class="switch" for="webhook-enabled">
          <input id="webhook-enabled" v-model="wh.enabled" name="webhook_enabled" type="checkbox"
                 :disabled="webhookBusy" @change="saveWebhook" />
          <span>{{ t('settings.webhookEnabled') }}</span>
        </label>
      </div>
      <div class="form-grid wide">
        <div class="field span-2">
          <label for="webhook-url">{{ t('settings.webhookUrl') }}</label>
          <input id="webhook-url" v-model="wh.url" name="webhook_url" type="url" autocomplete="url"
                 :placeholder="t('settings.webhookUrlPh')" :disabled="webhookBusy" />
        </div>
        <div class="field span-2">
          <label for="webhook-secret">{{ t('settings.webhookSecret') }}</label>
          <input id="webhook-secret" v-model="wh.secret" name="webhook_secret" type="password" autocomplete="new-password"
                 :placeholder="t('settings.webhookSecretPh')" :disabled="webhookBusy" />
        </div>
      </div>
      <div class="actions-row wrap">
        <button class="btn" type="submit" :disabled="webhookBusy">{{ t('settings.save') }}</button>
        <button class="btn ghost" type="button" :disabled="webhookBusy" @click="testWebhook">{{ t('settings.testSend') }}</button>
      </div>
      <p v-if="whMsg" class="feedback" :class="whOk ? 'ok' : 'err'" :role="whOk ? 'status' : 'alert'">{{ whMsg }}</p>
    </form>
    </section>

    <div id="backup" class="grid two settings-anchor">
      <!-- 数据备份与恢复 -->
      <div class="card sect panel-card data-card">
        <div class="panel-head compact">
          <div>
            <div class="panel-title"><span class="panel-signal"></span>{{ t('backup.title') }}</div>
            <p class="muted">{{ t('backup.tip') }}</p>
          </div>
        </div>
        <div class="actions-row wrap">
          <button class="btn ghost" type="button" :disabled="backupExporting || backupImporting" @click="exportData">⬇️ {{ t('backup.export') }}</button>
          <button class="btn ghost file-btn" type="button" :disabled="backupExporting || backupImporting" @click="openBackupFilePicker">⬆️ {{ t('backup.import') }}</button>
          <input id="backup-import-file" ref="backupFileInput" class="sr-only" name="backup_import_file" type="file"
                 accept="application/json,.json" tabindex="-1" aria-hidden="true" :disabled="backupImporting" @change="importData" />
        </div>
        <label class="switch replace-switch" for="backup-import-replace">
          <input id="backup-import-replace" v-model="importReplace" name="backup_import_replace" type="checkbox" :disabled="backupImporting" />
          <span>{{ t('backup.replace') }}</span>
        </label>
        <p v-if="backupMsg" class="feedback" :class="backupOk ? 'ok' : 'err'" :role="backupOk ? 'status' : 'alert'">{{ backupMsg }}</p>
      </div>

      <!-- 管理员：整站备份与恢复 -->
      <div id="backup-all" class="card sect panel-card data-card admin-data" v-if="auth.user?.is_admin">
        <div class="panel-head compact">
          <div>
            <div class="panel-title"><span class="panel-signal warn"></span>{{ t('backupAll.title') }}</div>
            <p class="muted">{{ t('backupAll.tip') }}</p>
          </div>
        </div>
        <div class="actions-row wrap">
          <button class="btn ghost" type="button" :disabled="backupAllExporting || backupAllImporting" @click="exportAll">⬇️ {{ t('backupAll.export') }}</button>
          <button class="btn ghost file-btn" type="button" :disabled="backupAllExporting || backupAllImporting" @click="openBackupAllFilePicker">⬆️ {{ t('backupAll.import') }}</button>
          <input id="backup-all-import-file" ref="backupAllFileInput" class="sr-only" name="backup_all_import_file" type="file"
                 accept="application/json,.json" tabindex="-1" aria-hidden="true" :disabled="backupAllImporting" @change="importAll" />
        </div>
        <label class="switch replace-switch" for="backup-all-import-replace">
          <input id="backup-all-import-replace" v-model="importAllReplace" name="backup_all_import_replace" type="checkbox" :disabled="backupAllImporting" />
          <span>{{ t('backupAll.replace') }}</span>
        </label>
        <p v-if="backupAllMsg" class="feedback" :class="backupAllOk ? 'ok' : 'err'" :role="backupAllOk ? 'status' : 'alert'">{{ backupAllMsg }}</p>
      </div>
    </div>

    <!-- 系统信息 -->
    <div id="system" class="card sect panel-card settings-anchor">
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
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import api from '../api'
import CalendarFeedManager from '../components/settings/CalendarFeedManager.vue'
import CategoryManager from '../components/settings/CategoryManager.vue'
import CurrencyManager from '../components/settings/CurrencyManager.vue'
import PaymentMethodManager from '../components/settings/PaymentMethodManager.vue'
import { useAuth } from '../stores/auth'
import { formatDateTimeInZone } from '../utils/time'

const { t } = useI18n()
const auth = useAuth()
const route = useRoute()

const settingsNavItems = computed(() => [
  { id: 'preferences', label: 'settings.navPreferences' },
  { id: 'account', label: 'settings.navAccount' },
  { id: 'rates-and-reference-data', label: 'settings.navReferenceData' },
  { id: 'calendar-feed', label: 'settings.navCalendarFeed' },
  { id: 'notifications', label: 'settings.navNotifications' },
  { id: 'backup', label: 'settings.navBackup' },
  ...(auth.user?.is_admin ? [{ id: 'backup-all', label: 'settings.navBackupAll' }] : []),
  { id: 'system', label: 'settings.navSystem' }
])
const activeSection = computed(() => route.hash.slice(1))

async function scrollToSettingsSection(hash) {
  const id = hash.startsWith('#') ? hash.slice(1) : ''
  if (!settingsNavItems.value.some((item) => item.id === id)) return
  await nextTick()
  document.getElementById(id)?.scrollIntoView({ block: 'start' })
}

watch(() => route.hash, scrollToSettingsSection)

const themes = [
  { v: 'light', k: 'Light', c: '#ffffff' },
  { v: 'dark', k: 'Dark', c: '#181d2e' },
  { v: 'ocean', k: 'Ocean', c: '#06b6d4' },
  { v: 'forest', k: 'Forest', c: '#16a34a' },
  { v: 'purple', k: 'Purple', c: '#9333ea' }
]

const theme = ref(auth.user?.theme || 'light')
const themeSaving = ref(false)
const baseCurrency = ref(auth.user?.base_currency || 'CNY')
const currencySaving = ref(false)
const monthlyBudget = ref(auth.user?.monthly_budget ?? null)
const budgetSaving = ref(false)
const prefMsg = ref('')
const prefOk = ref(true)
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
const barkBusy = ref(false)
const wh = reactive({
  enabled: auth.user?.webhook_enabled || false,
  url: auth.user?.webhook_url || '',
  secret: auth.user?.webhook_secret || ''
})
const whMsg = ref('')
const whOk = ref(false)
const webhookBusy = ref(false)
const currencies = ref([])
const rateMsg = ref('')
const rateOk = ref(false)
const ratesRefreshing = ref(false)
const rates = ref({ base: baseCurrency.value, updated_at: null, items: [] })
const tgMsg = ref('')
const tgOk = ref(false)
const tgBusy = ref(false)

const acc = reactive({ username: auth.user?.username || '', email: auth.user?.email || '' })
const pwd = reactive({ old_password: '', new_password: '' })
const accMsg = ref('')
const accOk = ref(false)
const accountSaving = ref(false)
const passwordSaving = ref(false)
const sys = ref(null)

const backupMsg = ref('')
const backupOk = ref(false)
const importReplace = ref(false)
const backupExporting = ref(false)
const backupImporting = ref(false)
const backupFileInput = ref(null)

const backupAllMsg = ref('')
const backupAllOk = ref(false)
const importAllReplace = ref(false)
const backupAllExporting = ref(false)
const backupAllImporting = ref(false)
const backupAllFileInput = ref(null)

const currentThemeLabel = computed(() => {
  const item = themes.find((x) => x.v === theme.value)
  return item ? t('settings.theme' + item.k) : theme.value
})
const enabledChannels = computed(() => (
  Number(Boolean(tg.enabled)) + Number(Boolean(bk.enabled)) + Number(Boolean(wh.enabled))
))

function downloadBackup(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function openBackupFilePicker() {
  if (backupImporting.value || backupExporting.value) return
  backupFileInput.value?.click()
}

async function exportData() {
  if (backupExporting.value || backupImporting.value) return
  backupMsg.value = ''
  backupExporting.value = true
  try {
    const { data } = await api.get('/api/backup/export')
    const stamp = new Date().toISOString().slice(0, 10)
    downloadBackup(data, `subly-backup-${stamp}.json`)
    backupOk.value = true
    backupMsg.value = t('backup.exportOk')
  } catch (e) {
    backupOk.value = false
    backupMsg.value = e.response?.data?.detail || 'Error'
  } finally {
    backupExporting.value = false
  }
}

async function importData(e) {
  const input = e.currentTarget
  if (backupImporting.value) {
    input.value = ''
    return
  }
  const file = input.files?.[0]
  if (!file) return
  backupMsg.value = ''
  backupImporting.value = true
  try {
    if (importReplace.value && !window.confirm(t('backup.replaceConfirm'))) return
    const json = JSON.parse(await file.text())
    const { data } = await api.post('/api/backup/import', { data: json, replace: importReplace.value })
    backupOk.value = true
    backupMsg.value = t('backup.importOk', { n: data.imported })
  } catch (err) {
    backupOk.value = false
    backupMsg.value = err.response?.data?.detail || t('backup.importFail')
  } finally {
    backupImporting.value = false
    input.value = ''
  }
}

function openBackupAllFilePicker() {
  if (backupAllImporting.value || backupAllExporting.value) return
  backupAllFileInput.value?.click()
}

async function exportAll() {
  if (backupAllExporting.value || backupAllImporting.value) return
  backupAllMsg.value = ''
  backupAllExporting.value = true
  try {
    const { data } = await api.get('/api/backup/export-all')
    const stamp = new Date().toISOString().slice(0, 10)
    downloadBackup(data, `subly-full-backup-${stamp}.json`)
    backupAllOk.value = true
    backupAllMsg.value = t('backupAll.exportOk', { n: data.users?.length || 0 })
  } catch (e) {
    backupAllOk.value = false
    backupAllMsg.value = e.response?.data?.detail || 'Error'
  } finally {
    backupAllExporting.value = false
  }
}

async function importAll(e) {
  const input = e.currentTarget
  if (backupAllImporting.value) {
    input.value = ''
    return
  }
  const file = input.files?.[0]
  if (!file) return
  backupAllMsg.value = ''
  backupAllImporting.value = true
  try {
    if (!window.confirm(t(importAllReplace.value ? 'backupAll.replaceConfirm' : 'backupAll.importConfirm'))) return
    const json = JSON.parse(await file.text())
    const { data } = await api.post('/api/backup/import-all', { data: json, replace: importAllReplace.value })
    backupAllOk.value = true
    backupAllMsg.value = t('backupAll.importOk', { users: data.users, created: data.created_users, n: data.imported })
  } catch (err) {
    backupAllOk.value = false
    backupAllMsg.value = err.response?.data?.detail || t('backup.importFail')
  } finally {
    backupAllImporting.value = false
    input.value = ''
  }
}

async function saveAccount() {
  if (accountSaving.value) return
  accMsg.value = ''
  accountSaving.value = true
  try {
    await api.patch('/api/me/account', { username: acc.username, email: acc.email })
    await auth.fetchMe()
    accOk.value = true; accMsg.value = t('account.accountOk')
  } catch (e) {
    accOk.value = false; accMsg.value = e.response?.data?.detail || 'Error'
  } finally {
    accountSaving.value = false
  }
}
async function changePwd() {
  if (passwordSaving.value) return
  accMsg.value = ''
  passwordSaving.value = true
  try {
    await api.post('/api/me/password', pwd)
    pwd.old_password = ''; pwd.new_password = ''
    accOk.value = true; accMsg.value = t('account.pwdOk')
  } catch (e) {
    accOk.value = false; accMsg.value = e.response?.data?.detail || 'Error'
  } finally {
    passwordSaving.value = false
  }
}

async function changeTheme(nextTheme) {
  if (themeSaving.value || nextTheme === theme.value) return
  const savedTheme = theme.value
  theme.value = nextTheme
  themeSaving.value = true
  try {
    await auth.updateMe({ theme: theme.value })
  } catch (e) {
    theme.value = savedTheme
    prefOk.value = false
    prefMsg.value = e.response?.data?.detail || 'Error'
  } finally {
    themeSaving.value = false
  }
}
async function changeCurrency() {
  if (currencySaving.value) return
  const savedCurrency = auth.user?.base_currency || 'CNY'
  const hadBudget = monthlyBudget.value !== null && monthlyBudget.value !== ''
  prefMsg.value = ''
  currencySaving.value = true
  try {
    // 币种与预算必须同一请求更新，避免第一次成功、第二次失败后旧预算被按新币种解释。
    await auth.updateMe({
      base_currency: baseCurrency.value,
      ...(hadBudget ? { monthly_budget: null } : {})
    })
    if (hadBudget) {
      monthlyBudget.value = null
      prefOk.value = true
      prefMsg.value = t('settings.budgetClearedOnCurrencyChange')
    }
    loadRates()
  } catch (error) {
    baseCurrency.value = savedCurrency
    prefOk.value = false
    prefMsg.value = error.response?.data?.detail || t('common.networkError')
  } finally {
    currencySaving.value = false
  }
}
async function saveBudget() {
  if (budgetSaving.value) return
  const v = monthlyBudget.value
  budgetSaving.value = true
  try {
    await auth.updateMe({ monthly_budget: (v === '' || v === null) ? null : Number(v) })
    prefOk.value = true
    prefMsg.value = t('settings.saved')
  } catch (e) {
    prefOk.value = false
    prefMsg.value = e.response?.data?.detail || 'Error'
  } finally {
    budgetSaving.value = false
  }
}

function fmtTime(s) { return formatDateTimeInZone(s, sys.value?.timezone || 'Asia/Shanghai') }
async function loadCurrencies() {
  try { currencies.value = (await api.get('/api/currencies')).data || [] }
  catch { currencies.value = [] }
}
async function handleCurrencyChanged() {
  await Promise.all([loadCurrencies(), loadRates()])
}
async function loadRates() {
  try { rates.value = (await api.get('/api/currencies/rate-table')).data }
  catch { /* ignore */ }
}
async function persistTg() {
  try {
    await auth.updateMe({
      telegram_enabled: tg.enabled,
      telegram_bot_token: tg.bot_token,
      telegram_chat_id: tg.chat_id,
      telegram_admin_id: tg.admin_id,
      telegram_api_base: tg.api_base || null,
      telegram_proxy: tg.proxy || null
    })
    tgOk.value = true; tgMsg.value = t('settings.saved')
    return true
  } catch (e) {
    tgOk.value = false; tgMsg.value = e.response?.data?.detail || 'Error'
    return false
  }
}

async function saveTg() {
  if (tgBusy.value) return false
  tgBusy.value = true
  try {
    return await persistTg()
  } finally {
    tgBusy.value = false
  }
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

async function persistBark(ttl) {
  try {
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
  } catch (e) {
    bkOk.value = false; bkMsg.value = e.response?.data?.detail || 'Error'
    return false
  }
}

async function saveBark() {
  if (barkBusy.value) return false
  const ttl = normalizeBarkTtl()
  if (ttl === undefined) return false
  barkBusy.value = true
  try {
    return await persistBark(ttl)
  } finally {
    barkBusy.value = false
  }
}

async function testBark() {
  if (barkBusy.value) return
  const ttl = normalizeBarkTtl()
  if (ttl === undefined) return
  barkBusy.value = true
  try {
    const saved = await persistBark(ttl)
    if (!saved) return
    await api.post('/api/notifications/bark/test', { device_key: bk.device_key, server: bk.server || null, ttl })
    bkOk.value = true; bkMsg.value = t('settings.testOk')
  } catch (e) {
    bkOk.value = false; bkMsg.value = e.response?.data?.detail || 'Error'
  } finally {
    barkBusy.value = false
  }
}

async function persistWebhook() {
  try {
    await auth.updateMe({
      webhook_enabled: wh.enabled,
      webhook_url: wh.url || null,
      webhook_secret: wh.secret || null
    })
    whOk.value = true; whMsg.value = t('settings.saved')
    return true
  } catch (e) {
    whOk.value = false; whMsg.value = e.response?.data?.detail || 'Error'
    return false
  }
}

async function saveWebhook() {
  if (webhookBusy.value) return false
  webhookBusy.value = true
  try {
    return await persistWebhook()
  } finally {
    webhookBusy.value = false
  }
}

async function testWebhook() {
  if (webhookBusy.value) return
  webhookBusy.value = true
  try {
    const saved = await persistWebhook()
    if (!saved) return
    await api.post('/api/notifications/webhook/test')
    whOk.value = true; whMsg.value = t('settings.testOk')
  } catch (e) {
    whOk.value = false; whMsg.value = e.response?.data?.detail || 'Error'
  } finally {
    webhookBusy.value = false
  }
}

async function refreshRates() {
  if (ratesRefreshing.value) return
  rateMsg.value = ''
  ratesRefreshing.value = true
  try {
    await api.post('/api/currencies/rates/refresh')
    rateOk.value = true
    rateMsg.value = t('settings.ratesUpdated')
    await loadRates()
  } catch (e) {
    rateOk.value = false
    rateMsg.value = e.response?.data?.detail || 'Error'
  } finally {
    ratesRefreshing.value = false
  }
}
async function checkBot() {
  if (tgBusy.value) return
  tgBusy.value = true
  try {
    const saved = await persistTg()
    if (!saved) return
    const { data } = await api.get('/api/notifications/telegram/me')
    tgOk.value = true; tgMsg.value = `${t('settings.botOk')}: @${data.result?.username}`
  } catch (e) {
    tgOk.value = false; tgMsg.value = t('settings.botFail') + ': ' + (e.response?.data?.detail || '')
  } finally {
    tgBusy.value = false
  }
}
async function testSend() {
  if (tgBusy.value) return
  tgBusy.value = true
  try {
    const saved = await persistTg()
    if (!saved) return
    await api.post('/api/notifications/telegram/test', { chat_id: tg.chat_id })
    tgOk.value = true; tgMsg.value = t('settings.testOk')
  } catch (e) {
    tgOk.value = false; tgMsg.value = e.response?.data?.detail || 'Error'
  } finally {
    tgBusy.value = false
  }
}
async function getUpdates() {
  if (tgBusy.value) return
  tgBusy.value = true
  try {
    const saved = await persistTg()
    if (!saved) return
    const { data } = await api.get('/api/notifications/telegram/updates')
    const ids = (data.result || []).map((u) => u.message?.chat?.id).filter(Boolean)
    tgOk.value = true
    tgMsg.value = ids.length ? 'Chat IDs: ' + [...new Set(ids)].join(', ') : 'No messages yet'
    if (ids.length) tg.chat_id = String(ids[ids.length - 1])
  } catch (e) {
    tgOk.value = false; tgMsg.value = e.response?.data?.detail || 'Error'
  } finally {
    tgBusy.value = false
  }
}

onMounted(async () => {
  const initialHash = route.hash
  await loadCurrencies()
  try { sys.value = (await api.get('/api/system/info')).data }
  catch { sys.value = null }
  loadRates()
  await scrollToSettingsSection(initialHash)
})
</script>

<style scoped>
.settings-page { display: flex; flex-direction: column; gap: 16px; }
.settings-nav { position: sticky; top: 8px; z-index: 20; display: flex; gap: 8px; padding: 8px; overflow-x: auto;
  border: 1px solid var(--border); border-radius: 14px; background: color-mix(in srgb, var(--surface) 92%, transparent); backdrop-filter: blur(12px); }
.settings-nav-link { flex: 0 0 auto; min-height: var(--tap-size); display: inline-flex; align-items: center; padding: 8px 12px;
  border-radius: 10px; color: var(--text-soft); font-size: 13px; font-weight: 750; white-space: nowrap; }
.settings-nav-link:hover { background: var(--surface-2); color: var(--text); }
.settings-nav-link[aria-current="location"] { background: var(--primary-soft); color: var(--primary); }
.settings-anchor { scroll-margin-top: 82px; }
.settings-group { display: flex; flex-direction: column; gap: 16px; }
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
.ok { color: var(--success-text); }
.err { color: var(--danger-text); word-break: break-all; }
.actions-row { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
.actions-row.wrap { flex-wrap: wrap; }
.budget-row { display: flex; align-items: center; gap: 8px; }
.budget-row input { flex: 1 1 0; min-width: 0; }
.budget-hint { font-size: 12px; margin: 4px 0 0; }
.switch { display: inline-flex; align-items: center; gap: 7px; min-height: var(--tap-size); font-size: 13px; color: var(--text-soft); cursor: pointer; width: auto; margin: 0; }
.switch input { width: auto; }
.replace-switch { margin-top: 12px; align-items: flex-start; }
.theme-fieldset { min-width: 0; margin: 0; padding: 0; border: 0; }
.theme-fieldset legend { padding: 0; }
.theme-picker { display: flex; gap: 10px; margin: 6px 0 8px; }
.th { width: var(--tap-size); height: var(--tap-size); border-radius: 50%; border: 2px solid var(--border); cursor: pointer; padding: 0; }
.th.on { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft); }
.rate-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; }
.rate { border: 1px solid var(--border); border-radius: 12px; padding: 11px 12px; background: var(--surface-2);
  transition: transform .15s ease, border-color .15s ease; }
.rate:hover { transform: translateY(-2px); border-color: var(--primary); }
.rate-code { font-weight: 750; font-size: 14px; }
.rate-val { font-size: 13px; color: var(--text); margin-top: 4px; }
.reference-section { display: flex; flex-direction: column; gap: 12px; }
.section-intro h2 { margin: 0; font-size: 18px; }
.section-intro p { margin: 5px 0 0; font-size: 13px; line-height: 1.6; }
.reference-grid { align-items: start; }
.hint-box { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px 10px; padding: 12px;
  border: 1px solid var(--border); border-radius: 13px; background: color-mix(in srgb, var(--surface-2) 82%, transparent); margin-bottom: 12px; }
.hint-box span { color: var(--signal-cyan); font-size: 12px; }
.hint-box p { margin: 0; color: var(--text-soft); font-size: 13px; line-height: 1.5; }
.tip-text { margin-top: 0; font-size: 13px; line-height: 1.6; }
.file-btn { width: auto; margin: 0; }
.data-card { min-height: 100%; }
.admin-data { border-color: color-mix(in srgb, var(--warning) 35%, var(--border)); }
.status-ok { background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success-text); }
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
  .settings-nav { top: calc(54px + env(safe-area-inset-top)); margin-inline: -16px; border-inline: 0; border-radius: 0; }
  .settings-anchor { scroll-margin-top: calc(124px + env(safe-area-inset-top)); }
  .settings-hero { padding: 18px; }
  .hero-copy p { line-height: 1.6; }
  .hero-metrics { grid-template-columns: 1fr; }
  .metric-card b, .panel-title, .rate-code, .rate-val, .si b { overflow-wrap: anywhere; }
  .form-grid, .form-grid.wide { grid-template-columns: 1fr; gap: 8px; }
  .field.span-2 { grid-column: auto; }
  .panel-card { border-radius: 14px; }
  .panel-head { align-items: stretch; gap: 10px; margin-bottom: 10px; }
  .panel-head p { font-size: 12px; line-height: 1.55; }
  .panel-head .btn, .actions-row .btn, .actions-row .file-btn { flex: 1 1 100%; justify-content: center; text-align: center; }
  .actions-row { align-items: stretch; gap: 8px; }
  .switch { width: 100%; justify-content: space-between; min-height: 44px; padding: 8px 0; }
  .theme-picker { flex-wrap: wrap; }
  .rate-grid, .sys-grid { grid-template-columns: 1fr; }
  .hint-box { grid-template-columns: 1fr; gap: 6px; }
  .hint-box span { font-weight: 800; }
}
</style>
