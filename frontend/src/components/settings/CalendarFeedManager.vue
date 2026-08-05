<template>
  <section class="card calendar-feed-card" aria-labelledby="calendar-feed-title">
    <div class="feed-head">
      <div>
        <div class="feed-eyebrow">{{ t('settings.calendarFeedEyebrow') }}</div>
        <h2 id="calendar-feed-title">
          <span class="feed-signal" aria-hidden="true"></span>
          {{ t('settings.calendarFeed') }}
        </h2>
        <p class="muted">{{ t('settings.calendarFeedTip') }}</p>
      </div>
      <span class="feed-status" :class="enabled ? 'enabled' : 'disabled'">
        <span aria-hidden="true"></span>
        {{ enabled ? t('settings.calendarFeedEnabled') : t('settings.calendarFeedDisabled') }}
      </span>
    </div>

    <div class="feed-route" aria-hidden="true">
      <span class="route-node source">S</span>
      <span class="route-line"></span>
      <span class="route-pulse"></span>
      <span class="route-line"></span>
      <span class="route-node target">31</span>
    </div>

    <div class="feed-copy">
      <p>{{ enabled ? t('settings.calendarFeedEnabledTip') : t('settings.calendarFeedDisabledTip') }}</p>
      <p class="muted">{{ t('settings.calendarFeedHttpsTip') }}</p>
    </div>

    <div v-if="feedUrl" class="credential-box">
      <label for="calendar-feed-url">{{ t('settings.calendarFeedUrl') }}</label>
      <div class="credential-row">
        <input id="calendar-feed-url" :value="feedUrl" readonly spellcheck="false" autocomplete="off" />
        <button type="button" class="btn" :disabled="busy" @click="copyUrl">
          {{ copied ? t('settings.calendarFeedCopied') : t('settings.calendarFeedCopy') }}
        </button>
      </div>
      <p class="credential-warning">{{ t('settings.calendarFeedCredentialWarning') }}</p>
      <p v-if="!isHttps" class="https-warning" role="alert">{{ t('settings.calendarFeedInsecureWarning') }}</p>
    </div>

    <div class="feed-actions">
      <button v-if="!enabled" type="button" class="btn" :disabled="busy || loading" @click="generate">
        {{ t('settings.calendarFeedGenerate') }}
      </button>
      <template v-else>
        <button type="button" class="btn ghost" :disabled="busy || loading" @click="requestReset">
          {{ t('settings.calendarFeedReset') }}
        </button>
        <button type="button" class="btn danger" :disabled="busy || loading" @click="requestRevoke">
          {{ t('settings.calendarFeedRevoke') }}
        </button>
      </template>
    </div>

    <p v-if="message" class="feedback" :class="ok ? 'ok' : 'err'" role="status">{{ message }}</p>

    <AppModal
      v-model="confirmOpen"
      :title="confirm.state.value?.title || ''"
      :close-label="t('common.close')"
      @close="confirm.reset"
    >
      <p>{{ confirm.state.value?.message }}</p>
      <template #footer>
        <button type="button" class="btn ghost" @click="confirm.reset">{{ t('sub.cancel') }}</button>
        <button type="button" class="btn" :class="{ danger: confirm.state.value?.danger }" @click="confirm.confirm">
          {{ t('common.confirm') }}
        </button>
      </template>
    </AppModal>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../api'
import { useConfirm } from '../../composables/useConfirm'
import AppModal from '../AppModal.vue'

const { t } = useI18n()
const confirm = useConfirm()
const confirmOpen = computed({
  get: () => Boolean(confirm.state.value?.open),
  set: (value) => { if (!value) confirm.reset() }
})
const enabled = ref(false)
const feedUrl = ref('')
const loading = ref(true)
const busy = ref(false)
const copied = ref(false)
const message = ref('')
const ok = ref(true)
const isHttps = computed(() => feedUrl.value.startsWith('https://'))
let copyTimer = null

function clearPlaintextUrl() {
  feedUrl.value = ''
  copied.value = false
}

async function loadStatus() {
  loading.value = true
  message.value = ''
  try {
    enabled.value = Boolean((await api.get('/api/calendar-feed/status')).data?.enabled)
  } catch (error) {
    ok.value = false
    message.value = error.response?.data?.detail || t('common.networkError')
  } finally {
    loading.value = false
  }
}

async function generate() {
  if (busy.value) return
  busy.value = true
  message.value = ''
  try {
    const data = (await api.post('/api/calendar-feed/generate')).data
    enabled.value = true
    feedUrl.value = data.feed_url || ''
    ok.value = true
    message.value = t('settings.calendarFeedGenerated')
  } catch (error) {
    ok.value = false
    message.value = error.response?.data?.detail || t('common.networkError')
  } finally {
    busy.value = false
  }
}

function requestReset() {
  confirm.open({
    title: t('settings.calendarFeedReset'),
    message: t('settings.calendarFeedResetConfirm'),
    onConfirm: reset
  })
}

async function reset() {
  if (busy.value) return
  busy.value = true
  message.value = ''
  try {
    const data = (await api.post('/api/calendar-feed/reset')).data
    feedUrl.value = data.feed_url || ''
    enabled.value = true
    ok.value = true
    message.value = t('settings.calendarFeedResetDone')
  } catch (error) {
    ok.value = false
    message.value = error.response?.data?.detail || t('common.networkError')
  } finally {
    busy.value = false
  }
}

function requestRevoke() {
  confirm.open({
    title: t('settings.calendarFeedRevoke'),
    message: t('settings.calendarFeedRevokeConfirm'),
    danger: true,
    onConfirm: revoke
  })
}

async function revoke() {
  if (busy.value) return
  busy.value = true
  message.value = ''
  try {
    await api.delete('/api/calendar-feed')
    enabled.value = false
    clearPlaintextUrl()
    ok.value = true
    message.value = t('settings.calendarFeedRevoked')
  } catch (error) {
    ok.value = false
    message.value = error.response?.data?.detail || t('common.networkError')
  } finally {
    busy.value = false
  }
}

async function copyUrl() {
  if (!feedUrl.value) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(feedUrl.value)
    } else {
      const input = document.createElement('textarea')
      input.value = feedUrl.value
      input.setAttribute('readonly', '')
      input.style.position = 'fixed'
      input.style.opacity = '0'
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      input.remove()
    }
    copied.value = true
    if (copyTimer) window.clearTimeout(copyTimer)
    copyTimer = window.setTimeout(() => { copied.value = false }, 2000)
  } catch {
    ok.value = false
    message.value = t('settings.calendarFeedCopyFailed')
  }
}

onMounted(loadStatus)
onBeforeUnmount(() => {
  clearPlaintextUrl()
  if (copyTimer) window.clearTimeout(copyTimer)
})
</script>

<style scoped>
.calendar-feed-card { position: relative; overflow: hidden; padding: 20px; border-color: color-mix(in srgb, var(--signal-cyan) 30%, var(--border)); }
.calendar-feed-card::before { content: ''; position: absolute; width: 260px; height: 260px; right: -120px; top: -150px; border-radius: 50%; background: color-mix(in srgb, var(--signal-cyan) 10%, transparent); pointer-events: none; }
.feed-head { position: relative; display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.feed-eyebrow { margin-bottom: 6px; color: var(--signal-cyan); font: 800 11px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .16em; }
.feed-head h2 { display: flex; align-items: center; gap: 9px; margin: 0; font-size: 18px; }
.feed-head p { max-width: 680px; margin: 6px 0 0; font-size: 13px; line-height: 1.6; }
.feed-signal { width: 9px; height: 9px; border-radius: 50%; background: var(--signal-cyan); box-shadow: 0 0 0 4px color-mix(in srgb, var(--signal-cyan) 13%, transparent), 0 0 18px color-mix(in srgb, var(--signal-cyan) 45%, transparent); }
.feed-status { display: inline-flex; align-items: center; gap: 7px; flex-shrink: 0; min-height: 32px; padding: 6px 10px; border: 1px solid var(--border); border-radius: 999px; font-size: 12px; font-weight: 800; }
.feed-status span { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.feed-status.enabled { color: var(--success); background: color-mix(in srgb, var(--success) 10%, transparent); }
.feed-status.disabled { color: var(--text-soft); background: var(--surface-2); }
.feed-route { display: flex; align-items: center; max-width: 580px; margin: 22px 0 16px; }
.route-node { display: grid; place-items: center; width: 42px; height: 42px; border: 1px solid color-mix(in srgb, var(--signal-cyan) 40%, var(--border)); border-radius: 12px; background: var(--surface-2); color: var(--signal-cyan); font: 850 14px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
.route-line { height: 1px; flex: 1; background: linear-gradient(90deg, var(--border), var(--signal-cyan)); }
.route-line:nth-of-type(4) { background: linear-gradient(90deg, var(--signal-cyan), var(--border)); }
.route-pulse { width: 12px; height: 12px; border: 3px solid var(--surface); border-radius: 50%; background: var(--signal-cyan); box-shadow: 0 0 0 4px color-mix(in srgb, var(--signal-cyan) 14%, transparent), 0 0 18px color-mix(in srgb, var(--signal-cyan) 56%, transparent); }
.feed-copy p { margin: 0; font-size: 13px; line-height: 1.65; }
.feed-copy .muted { margin-top: 4px; }
.credential-box { margin-top: 16px; padding: 14px; border: 1px solid color-mix(in srgb, var(--warning) 40%, var(--border)); border-radius: 14px; background: color-mix(in srgb, var(--warning) 6%, var(--surface-2)); }
.credential-box label { margin-top: 0; }
.credential-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
.credential-row input { min-width: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.credential-row .btn { min-height: 44px; }
.credential-warning, .https-warning { margin: 8px 0 0; font-size: 12px; line-height: 1.55; }
.credential-warning { color: var(--warning); }
.https-warning { color: var(--danger); }
.feed-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.feed-actions .btn { min-height: 44px; }
.feedback { margin: 10px 0 0; font-size: 13px; line-height: 1.5; }
.ok { color: var(--success); }
.err { color: var(--danger); overflow-wrap: anywhere; }
@media (max-width: 720px) {
  .calendar-feed-card { padding: 16px; }
  .feed-head { flex-direction: column; gap: 10px; }
  .feed-status { align-self: flex-start; }
  .feed-route { margin-top: 18px; }
  .credential-row { grid-template-columns: 1fr; }
  .feed-actions .btn { flex: 1 1 100%; }
}
</style>
