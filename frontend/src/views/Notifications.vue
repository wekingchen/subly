<template>
  <div class="notify-page">
    <section class="notify-hero card radar-grid-bg" aria-labelledby="notification-title">
      <div class="hero-copy">
        <div class="hero-kicker"><span class="signal-dot"></span> {{ t('notify.kicker') }}</div>
        <h1 id="notification-title" tabindex="-1">{{ t('notify.title') }}</h1>
        <p class="muted">{{ t('notify.subtitle') }}</p>
      </div>
      <div class="hero-actions">
        <button
          v-if="auth.user?.is_admin"
          class="btn"
          type="button"
          :disabled="scanBusy"
          @click="runScan"
        >
          {{ scanBusy ? t('notify.scanning') : t('notify.runScan') }}
        </button>
      </div>
      <div class="notify-metrics" aria-label="投递状态概览">
        <div class="metric-card">
          <span>{{ t('notify.total') }}</span>
          <b class="mono-data">{{ summary.total || 0 }}</b>
        </div>
        <div class="metric-card pending">
          <span>{{ t('notify.pending') }}</span>
          <b class="mono-data">{{ summary.pending || 0 }}</b>
        </div>
        <div class="metric-card retry">
          <span>{{ t('notify.retryWait') }}</span>
          <b class="mono-data">{{ summary.retry_wait || 0 }}</b>
        </div>
        <div class="metric-card dead">
          <span>{{ t('notify.dead') }}</span>
          <b class="mono-data">{{ summary.dead || 0 }}</b>
        </div>
      </div>
      <p v-if="message" class="scan-message" :class="{ bad: !messageOk }" aria-live="polite">
        {{ message }}
      </p>
    </section>

    <section class="queue-section" aria-label="通知投递队列">
      <div class="queue-toolbar">
        <div class="filter-label">{{ t('notify.filterLabel') }}</div>
        <div class="filter-row">
          <button
            v-for="option in filterOptions"
            :key="option.value"
            type="button"
            class="filter-btn"
            :class="{ active: filter === option.value }"
            :aria-pressed="filter === option.value"
            @click="filter = option.value"
          >
            {{ option.label }}
            <span class="mono-data">{{ option.count }}</span>
          </button>
        </div>
      </div>

      <div v-if="loading" class="card empty-state" aria-live="polite">正在加载投递队列…</div>

      <div v-else-if="visibleItems.length" class="queue-list">
        <article
          v-for="item in visibleItems"
          :key="item.id"
          class="card delivery-card"
          :class="`state-${item.status}`"
        >
          <div class="queue-rail" aria-hidden="true">
            <span class="rail-dot"></span>
          </div>

          <div class="delivery-main">
            <div class="delivery-head">
              <div class="delivery-identity">
                <div class="status-line">
                  <span class="status-chip" :class="`status-${item.status}`">
                    {{ statusLabel(item.status) }}
                  </span>
                  <span class="tag chan">{{ channelLabel(item.channel) }}</span>
                  <span class="delivery-id mono-data">#{{ item.id }}</span>
                </div>
                <h2>{{ item.subscription_name }}</h2>
              </div>
              <div class="delivery-time">
                <span>{{ t('notify.createdAt') }}</span>
                <b class="mono-data">{{ fmt(item.created_at) || '—' }}</b>
              </div>
            </div>

            <dl class="delivery-facts">
              <div>
                <dt>{{ t('notify.timing') }}</dt>
                <dd>{{ formatDaysBefore(item.days_before) }}</dd>
              </div>
              <div>
                <dt>{{ t('notify.renewalDate') }}</dt>
                <dd class="mono-data">{{ item.renewal_date }}</dd>
              </div>
              <div>
                <dt>{{ t('notify.attempts') }}</dt>
                <dd class="mono-data">{{ item.attempt_count }} / 6</dd>
              </div>
              <div v-if="item.next_attempt_at">
                <dt>{{ t('notify.nextRetry') }}</dt>
                <dd class="mono-data">{{ fmt(item.next_attempt_at) }}</dd>
              </div>
            </dl>

            <div v-if="item.last_error" class="safe-error">
              <span>{{ t('notify.lastError') }}</span>
              <code>{{ item.last_error }}</code>
            </div>

            <div class="delivery-actions">
              <button
                type="button"
                class="text-action"
                :aria-expanded="expandedId === item.id"
                :aria-controls="`attempts-${item.id}`"
                @click="toggleAttempts(item)"
              >
                {{ t('notify.attemptHistory') }}
                <span aria-hidden="true">{{ expandedId === item.id ? '−' : '+' }}</span>
              </button>
              <button
                v-if="canRetry(item)"
                type="button"
                class="btn retry-btn"
                :disabled="isRetrying(item.id)"
                @click="retry(item)"
              >
                {{ isRetrying(item.id) ? t('notify.retrying') : t('notify.retry') }}
              </button>
            </div>

            <div
              v-if="expandedId === item.id"
              :id="`attempts-${item.id}`"
              class="attempt-panel"
            >
              <p v-if="attemptLoadingId === item.id" class="muted">正在加载尝试记录…</p>
              <ol v-else-if="attempts[item.id]?.length" class="attempt-list">
                <li v-for="attempt in attempts[item.id]" :key="attempt.id">
                  <div>
                    <b>{{ attemptLabel(attempt) }}</b>
                    <span class="attempt-status" :class="attempt.status">
                      {{ attempt.status === 'sent' ? t('notify.sent') : t('notify.failed') }}
                    </span>
                  </div>
                  <span class="mono-data muted">{{ fmt(attempt.sent_at) }}</span>
                  <code v-if="attempt.message">{{ attempt.message }}</code>
                </li>
              </ol>
              <p v-else class="muted">{{ t('notify.noAttempts') }}</p>
            </div>
          </div>
        </article>
      </div>

      <div v-else class="card empty-state">
        <span class="signal-dot"></span>
        <div>
          <b>{{ t('notify.empty') }}</b>
          <p class="muted">{{ t('notify.emptyDesc') }}</p>
        </div>
      </div>
      <button
        v-if="!loading && visibleItems.length && hasMore"
        type="button"
        class="btn ghost load-more"
        :disabled="moreLoading"
        @click="loadMore"
      >
        {{ moreLoading ? t('notify.loadingMore') : t('notify.loadMore') }}
      </button>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import { useAuth } from '../stores/auth'
import { formatDateTimeInZone } from '../utils/time'

const { t } = useI18n()
const auth = useAuth()
const items = ref([])
const summary = ref({})
const timezone = ref('Asia/Shanghai')
const filter = ref('all')
const loading = ref(true)
const moreLoading = ref(false)
const hasMore = ref(false)
const nextCursor = ref(null)
const scanBusy = ref(false)
const retryingIds = ref(new Set())
const expandedId = ref(null)
const attempts = ref({})
const attemptLoadingId = ref(null)
const message = ref('')
const messageOk = ref(true)

const states = ['pending', 'sending', 'retry_wait', 'sent', 'dead', 'canceled']
let loadGeneration = 0

const visibleItems = computed(() => (
  filter.value === 'all'
    ? items.value
    : items.value.filter((item) => item.status === filter.value)
))

const filterOptions = computed(() => [
  { value: 'all', label: t('notify.total'), count: summary.value.total || 0 },
  ...states.map((state) => ({
    value: state,
    label: statusLabel(state),
    count: summary.value[state] || 0
  }))
])

function fmt(value) {
  return formatDateTimeInZone(value, timezone.value)
}

function channelLabel(channel) {
  return { telegram: 'Telegram', bark: 'Bark', webhook: 'Webhook' }[channel] || channel
}

function statusLabel(status) {
  return {
    pending: t('notify.pending'),
    sending: t('notify.sending'),
    retry_wait: t('notify.retryWait'),
    sent: t('notify.sent'),
    dead: t('notify.dead'),
    canceled: t('notify.canceled')
  }[status] || status
}

function attemptLabel(attempt) {
  const cycle = Number(attempt.retry_cycle || 0)
  return cycle > 0
    ? `第 ${cycle + 1} 轮 · 第 ${attempt.attempt_no} 次`
    : `第 ${attempt.attempt_no} 次`
}

function formatDaysBefore(n) {
  if (n < 0) return t('notify.daysAfter', { n: Math.abs(n) })
  if (n === 0) return t('notify.daysToday')
  return t('notify.daysBefore', { n })
}

function canRetry(item) {
  return item.status === 'dead' || item.status === 'retry_wait'
}

function isRetrying(id) {
  return retryingIds.value.has(id)
}

async function load({ append = false } = {}) {
  const generation = ++loadGeneration
  const requestedFilter = filter.value
  const cursor = append ? nextCursor.value : null
  if (append) moreLoading.value = true
  else {
    loading.value = true
    moreLoading.value = false
  }
  try {
    const params = { limit: 50 }
    if (requestedFilter !== 'all') params.status = requestedFilter
    if (cursor) {
      params.before_created_at = cursor.created_at
      params.before_id = cursor.id
    }
    const [outboxResponse, systemResponse] = await Promise.all([
      api.get('/api/notifications/outbox', { params }),
      api.get('/api/system/info')
    ])
    if (generation !== loadGeneration || requestedFilter !== filter.value) return
    const page = outboxResponse.data.items || []
    if (append) {
      const existingIds = new Set(items.value.map((item) => item.id))
      items.value = [...items.value, ...page.filter((item) => !existingIds.has(item.id))]
    } else {
      items.value = page
    }
    summary.value = outboxResponse.data.summary || {}
    hasMore.value = Boolean(outboxResponse.data.has_more)
    nextCursor.value = outboxResponse.data.next_cursor || null
    timezone.value = systemResponse.data.timezone || 'Asia/Shanghai'
  } catch {
    if (generation !== loadGeneration) return
    messageOk.value = false
    message.value = t('notify.loadFailed')
  } finally {
    if (generation === loadGeneration) {
      loading.value = false
      moreLoading.value = false
    }
  }
}

function loadMore() {
  if (!moreLoading.value && hasMore.value) load({ append: true })
}

async function refreshRow(id) {
  try {
    const row = (await api.get(`/api/notifications/outbox/${id}`)).data
    const index = items.value.findIndex((item) => item.id === id)
    if (index >= 0) {
      const previous = items.value[index]
      if (previous.status !== row.status) {
        summary.value = {
          ...summary.value,
          [previous.status]: Math.max((summary.value[previous.status] || 0) - 1, 0),
          [row.status]: (summary.value[row.status] || 0) + 1
        }
      }
      items.value.splice(index, 1, row)
    } else {
      items.value.unshift(row)
    }
  } catch {
    await load()
  }
}

async function runScan() {
  if (scanBusy.value) return
  scanBusy.value = true
  message.value = ''
  try {
    const result = (await api.post('/api/notifications/run-scan')).data
    messageOk.value = true
    message.value = t('notify.scanDone', {
      enqueued: result.enqueued || 0,
      existing: result.existing || 0
    })
    await load()
  } catch (error) {
    messageOk.value = false
    message.value = error.response?.data?.detail || t('notify.scanFailed')
  } finally {
    scanBusy.value = false
  }
}

async function retry(item) {
  if (isRetrying(item.id)) return
  retryingIds.value = new Set([...retryingIds.value, item.id])
  message.value = ''
  try {
    await api.post(`/api/notifications/outbox/${item.id}/retry`)
    await refreshRow(item.id)
    messageOk.value = true
    message.value = t('notify.retryQueued')
  } catch (error) {
    if (error.response?.status === 409) await refreshRow(item.id)
    messageOk.value = false
    message.value = error.response?.data?.detail || t('common.networkError')
  } finally {
    const next = new Set(retryingIds.value)
    next.delete(item.id)
    retryingIds.value = next
  }
}

async function toggleAttempts(item) {
  if (expandedId.value === item.id) {
    expandedId.value = null
    return
  }
  expandedId.value = item.id
  if (attempts.value[item.id]) return
  attemptLoadingId.value = item.id
  try {
    const data = (await api.get(`/api/notifications/outbox/${item.id}/attempts`)).data
    attempts.value = { ...attempts.value, [item.id]: data }
  } catch {
    attempts.value = { ...attempts.value, [item.id]: [] }
  } finally {
    attemptLoadingId.value = null
  }
}

watch(filter, () => {
  expandedId.value = null
  attempts.value = {}
  load()
})

onMounted(load)
</script>

<style scoped>
.notify-page { display: flex; flex-direction: column; gap: 18px; min-width: 0; }
.notify-hero { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 18px; align-items: start;
  background: linear-gradient(135deg, color-mix(in srgb, var(--surface) 88%, var(--radar-panel)), var(--surface)); }
.notify-hero > * { position: relative; z-index: 1; }
.hero-kicker { display: flex; align-items: center; gap: 8px; color: var(--text-soft); font-size: 12px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
h1 { margin: 8px 0; }
.hero-copy p { margin: 0; line-height: 1.7; max-width: 700px; }
.hero-actions { display: flex; justify-content: flex-end; }
.hero-actions .btn { min-height: 44px; }
.notify-metrics { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 10px; }
.metric-card { padding: 12px; border-radius: 14px; border: 1px solid var(--border); background: color-mix(in srgb, var(--surface-2) 82%, transparent); }
.metric-card span { display: block; font-size: 12px; color: var(--text-soft); margin-bottom: 5px; }
.metric-card b { font-size: 20px; }
.metric-card.pending { border-color: color-mix(in srgb, var(--signal-cyan) 32%, var(--border)); }
.metric-card.retry { border-color: color-mix(in srgb, var(--warning) 34%, var(--border)); }
.metric-card.dead { border-color: color-mix(in srgb, var(--danger) 34%, var(--border)); }
.scan-message { grid-column: 1 / -1; margin: 0; padding: 10px 12px; border-radius: 10px; background: color-mix(in srgb, var(--success) 12%, transparent); color: var(--success-text); }
.scan-message.bad { background: color-mix(in srgb, var(--danger) 12%, transparent); color: var(--danger-text); }
.queue-section { min-width: 0; }
.queue-toolbar { margin-bottom: 12px; }
.filter-label { margin-bottom: 8px; color: var(--text-soft); font-size: 12px; font-weight: 800; letter-spacing: .08em; }
.filter-row { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; scrollbar-width: thin; }
.filter-btn { min-height: 44px; padding: 8px 12px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); color: var(--text-soft); white-space: nowrap; cursor: pointer; }
.filter-btn .mono-data { margin-left: 6px; }
.filter-btn.active { border-color: var(--primary); color: var(--primary); background: color-mix(in srgb, var(--primary) 10%, var(--surface)); }
.queue-list { display: grid; gap: 12px; }
.delivery-card { position: relative; display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 12px; overflow: hidden; padding-left: 14px; }
.queue-rail { position: relative; min-height: 100%; }
.queue-rail::before { content: ''; position: absolute; top: -24px; bottom: -24px; left: 8px; width: 1px; background: var(--border); }
.rail-dot { position: absolute; top: 7px; left: 3px; width: 11px; height: 11px; border-radius: 50%; background: var(--text-soft); box-shadow: 0 0 0 4px var(--surface); }
.state-pending .rail-dot, .state-sending .rail-dot { background: var(--signal-cyan); box-shadow: 0 0 14px color-mix(in srgb, var(--signal-cyan) 55%, transparent), 0 0 0 4px var(--surface); }
.state-sent .rail-dot { background: var(--success); }
.state-retry_wait .rail-dot { background: var(--warning); }
.state-dead .rail-dot { background: var(--danger); }
.delivery-main { min-width: 0; }
.delivery-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.delivery-identity { min-width: 0; }
.delivery-identity h2 { margin: 9px 0 0; font-size: 18px; overflow-wrap: anywhere; }
.status-line { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.status-chip { display: inline-flex; min-height: 26px; align-items: center; padding: 3px 9px; border-radius: 999px; font-size: 12px; font-weight: 800; background: var(--surface-2); color: var(--text-soft); }
.status-pending, .status-sending { color: var(--signal-cyan); background: color-mix(in srgb, var(--signal-cyan) 13%, transparent); }
.status-retry_wait { color: var(--warning-text); background: color-mix(in srgb, var(--warning) 13%, transparent); }
.status-sent { color: var(--success-text); background: color-mix(in srgb, var(--success) 13%, transparent); }
.status-dead { color: var(--danger-text); background: color-mix(in srgb, var(--danger) 13%, transparent); }
.tag.chan { background: var(--surface-2); color: var(--text-soft); }
.delivery-id { font-size: 12px; color: var(--text-soft); }
.delivery-time { flex: 0 0 auto; text-align: right; }
.delivery-time span { display: block; color: var(--text-soft); font-size: 11px; margin-bottom: 4px; }
.delivery-time b { font-size: 12px; white-space: nowrap; }
.delivery-facts { display: grid; grid-template-columns: repeat(4, minmax(110px, 1fr)); gap: 8px; margin: 16px 0 0; }
.delivery-facts div { min-width: 0; padding: 10px; border-radius: 10px; background: var(--surface-2); }
.delivery-facts dt { color: var(--text-soft); font-size: 11px; margin-bottom: 4px; }
.delivery-facts dd { margin: 0; font-size: 13px; overflow-wrap: anywhere; }
.safe-error { display: flex; gap: 10px; align-items: center; margin-top: 12px; padding: 10px 12px; border-left: 3px solid var(--danger); background: color-mix(in srgb, var(--danger) 8%, transparent); }
.safe-error span { color: var(--text-soft); font-size: 12px; }
.safe-error code { overflow-wrap: anywhere; }
.delivery-actions { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-top: 14px; }
.text-action { min-height: 44px; border: 0; background: transparent; color: var(--primary); cursor: pointer; padding: 8px 0; font-weight: 700; }
.text-action span { margin-left: 5px; }
.retry-btn { min-height: 44px; }
.attempt-panel { margin-top: 8px; padding-top: 12px; border-top: 1px solid var(--border); }
.attempt-panel p { margin: 0; }
.attempt-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.attempt-list li { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 12px; padding: 10px; border-radius: 10px; background: var(--surface-2); }
.attempt-list code { grid-column: 1 / -1; overflow-wrap: anywhere; }
.attempt-status { margin-left: 8px; font-size: 12px; }
.attempt-status.sent { color: var(--success-text); }
.attempt-status.failed { color: var(--danger-text); }
.empty-state { display: flex; align-items: flex-start; gap: 12px; }
.empty-state b { display: block; margin-bottom: 4px; }
.empty-state p { margin: 0; line-height: 1.6; }
.load-more { display: block; min-height: 44px; margin: 14px auto 0; }
@media (max-width: 760px) {
  .notify-hero { grid-template-columns: 1fr; }
  .hero-actions .btn { width: 100%; }
  .notify-metrics { grid-template-columns: 1fr 1fr; }
  .delivery-head { flex-direction: column; }
  .delivery-time { text-align: left; }
  .delivery-facts { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 460px) {
  .notify-metrics { grid-template-columns: 1fr 1fr; }
  .delivery-card { grid-template-columns: 14px minmax(0, 1fr); gap: 8px; padding: 16px 12px 16px 10px; }
  .queue-rail::before { left: 6px; }
  .rail-dot { left: 1px; }
  .delivery-facts { grid-template-columns: 1fr; }
  .delivery-actions { align-items: stretch; flex-direction: column; }
  .delivery-actions > * { width: 100%; }
  .attempt-list li { grid-template-columns: 1fr; }
  .attempt-list code { grid-column: 1; }
}
</style>
