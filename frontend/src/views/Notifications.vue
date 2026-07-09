<template>
  <div class="notify-page">
    <section class="notify-hero card radar-grid-bg">
      <div class="hero-copy">
        <div class="hero-kicker"><span class="signal-dot"></span> 发报记录</div>
        <h1>{{ t('notify.title') }}</h1>
        <p class="muted">追踪 Telegram 与 Bark 的提醒发送结果，必要时立即触发一次续费扫描。</p>
      </div>
      <div class="hero-actions">
        <button v-if="auth.user?.is_admin" class="btn" @click="runScan">{{ t('notify.runScan') }}</button>
      </div>
      <div class="notify-metrics">
        <div class="metric-card">
          <span>总记录</span>
          <b class="mono-data">{{ logs.length }}</b>
        </div>
        <div class="metric-card ok">
          <span>{{ t('notify.sent') }}</span>
          <b class="mono-data">{{ sentCount }}</b>
        </div>
        <div class="metric-card bad">
          <span>{{ t('notify.failed') }}</span>
          <b class="mono-data">{{ failedCount }}</b>
        </div>
        <div class="metric-card">
          <span>最近信号</span>
          <b class="mono-data small-value">{{ latestTime || '—' }}</b>
        </div>
      </div>
    </section>

    <div v-if="logs.length" class="grid cards">
      <article v-for="l in logs" :key="l.id" class="card log-card" :class="statusClass(l)">
        <div class="lc-top">
          <div class="status-line">
            <span class="event-signal" :class="statusClass(l)"></span>
            <span class="tag" :class="l.status === 'sent' ? 'ok' : 'bad'">
              {{ l.status === 'sent' ? t('notify.sent') : t('notify.failed') }}
            </span>
            <span class="tag chan">{{ channelLabel(l.channel) }}</span>
          </div>
          <span class="muted mono-data sent-time">{{ fmt(l.sent_at) }}</span>
        </div>
        <div class="lc-body">{{ l.message }}</div>
        <div class="lc-foot muted">
          <span>{{ t('notify.daysBefore') }}: <b class="mono-data">{{ l.days_before }}</b></span>
        </div>
      </article>
    </div>

    <div v-else class="card empty-state">
      <span class="signal-dot"></span>
      <div>
        <b>{{ t('notify.empty') }}</b>
        <p class="muted">当前还没有提醒发报记录，可以点击上方按钮进行一次扫描。</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import { useAuth } from '../stores/auth'

const { t } = useI18n()
const auth = useAuth()
const logs = ref([])

const sentCount = computed(() => logs.value.filter((l) => l.status === 'sent').length)
const failedCount = computed(() => logs.value.filter((l) => l.status !== 'sent').length)
const latestTime = computed(() => {
  const latest = logs.value.reduce((out, item) => {
    if (!item.sent_at) return out
    const current = new Date(item.sent_at).getTime()
    return Number.isFinite(current) && current > out ? current : out
  }, 0)
  return latest ? new Date(latest).toLocaleString() : ''
})

function fmt(s) { return s ? new Date(s).toLocaleString() : '' }
function channelLabel(channel) { return channel === 'bark' ? 'Bark' : 'Telegram' }
function statusClass(log) { return log.status === 'sent' ? 'sent' : 'failed' }

async function load() { logs.value = (await api.get('/api/notifications/logs')).data }
async function runScan() { await api.post('/api/notifications/run-scan'); await load() }

onMounted(load)
</script>

<style scoped>
.notify-page { display: flex; flex-direction: column; gap: 16px; }
.notify-hero { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 18px; align-items: start;
  background: linear-gradient(135deg, color-mix(in srgb, var(--surface) 88%, var(--radar-panel)), var(--surface)); }
.notify-hero > * { position: relative; z-index: 1; }
.hero-kicker { display: flex; align-items: center; gap: 8px; color: var(--text-soft); font-size: 12px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
h1 { margin: 8px 0; }
.hero-copy p { margin: 0; line-height: 1.7; max-width: 640px; }
.hero-actions { display: flex; justify-content: flex-end; }
.notify-metrics { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 10px; }
.metric-card { padding: 12px; border-radius: 14px; border: 1px solid var(--border); background: color-mix(in srgb, var(--surface-2) 82%, transparent); }
.metric-card span { display: block; font-size: 12px; color: var(--text-soft); margin-bottom: 5px; }
.metric-card b { font-size: 18px; }
.metric-card.ok { border-color: color-mix(in srgb, var(--success) 30%, var(--border)); }
.metric-card.bad { border-color: color-mix(in srgb, var(--danger) 30%, var(--border)); }
.small-value { font-size: 13px !important; }
.cards { grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }
.log-card { position: relative; overflow: hidden; border-left: 4px solid var(--success); }
.log-card.failed { border-left-color: var(--danger); }
.log-card::before { content: ''; position: absolute; inset: 0; pointer-events: none; opacity: .45;
  background: radial-gradient(220px 120px at 0 0, color-mix(in srgb, var(--signal-cyan) 10%, transparent), transparent 70%); }
.log-card > * { position: relative; z-index: 1; }
.lc-top { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; margin-bottom: 12px; }
.status-line { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.event-signal { width: 8px; height: 8px; border-radius: 999px; background: var(--success); box-shadow: 0 0 14px color-mix(in srgb, var(--success) 45%, transparent); }
.event-signal.failed { background: var(--danger); box-shadow: 0 0 14px color-mix(in srgb, var(--danger) 45%, transparent); }
.lc-body { font-size: 14px; white-space: pre-wrap; line-height: 1.6; color: var(--text); }
.lc-foot { margin-top: 12px; font-size: 12px; }
.sent-time { font-size: 12px; text-align: right; white-space: nowrap; }
.tag.ok { background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success); }
.tag.bad { background: color-mix(in srgb, var(--danger) 18%, transparent); color: var(--danger); }
.tag.chan { background: var(--surface-2); color: var(--text-soft); }
.empty-state { display: flex; align-items: flex-start; gap: 12px; }
.empty-state b { display: block; margin-bottom: 4px; }
.empty-state p { margin: 0; line-height: 1.6; }
@media (max-width: 720px) {
  .notify-hero { grid-template-columns: 1fr; }
  .hero-actions .btn { width: 100%; }
  .notify-metrics { grid-template-columns: 1fr 1fr; }
  .lc-top { flex-direction: column; }
  .sent-time { text-align: left; }
}
@media (max-width: 460px) {
  .notify-metrics { grid-template-columns: 1fr; }
}
</style>
