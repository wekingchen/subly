<template>
  <div class="logs-page">
    <section class="logs-hero card radar-grid-bg">
      <div class="hero-copy">
        <div class="hero-kicker"><span class="signal-dot"></span> 系统遥测</div>
        <h1>{{ t('rtlog.title') }}</h1>
        <p class="muted">实时追踪系统动作、成员操作与后台任务信号；开启后每 4 秒拉取增量日志。</p>
      </div>
      <label class="switch hero-switch">
        <input type="checkbox" v-model="live" />
        <span class="dot" :class="{ on: live }"></span>
        {{ live ? t('rtlog.live') : t('rtlog.paused') }}
      </label>
      <div class="log-metrics">
        <div class="metric-card">
          <span>缓存日志</span>
          <b class="mono-data">{{ logs.length }}</b>
        </div>
        <div class="metric-card warn">
          <span>Warn</span>
          <b class="mono-data">{{ warnCount }}</b>
        </div>
        <div class="metric-card error">
          <span>Error</span>
          <b class="mono-data">{{ errorCount }}</b>
        </div>
        <div class="metric-card">
          <span>最后信号</span>
          <b class="mono-data small-value">{{ lastLogTime || '—' }}</b>
        </div>
      </div>
    </section>

    <div class="card terminal-card">
      <div class="terminal-head">
        <div class="terminal-title"><span class="terminal-led" :class="{ on: live }"></span>{{ t('rtlog.auto') }}</div>
        <span class="muted mono-data">limit=400 · interval=4s · tz={{ displayTimezone }}</span>
      </div>
      <div class="log-stream">
        <div v-for="l in logs" :key="l.id" class="log-line" :class="levelClass(l.level)">
          <span class="time mono-data">{{ fmt(l.created_at) }}</span>
          <span class="lvl" :class="levelClass(l.level)">{{ l.level }}</span>
          <span class="act">{{ l.action }}</span>
          <span v-if="l.user" class="usr">@{{ l.user }}</span>
          <span v-else class="usr muted">system</span>
          <span class="detail">{{ l.detail }}</span>
        </div>
        <div v-if="!logs.length" class="empty-log muted">{{ t('rtlog.empty') }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import { formatTimeInZone } from '../utils/time'

const { t } = useI18n()
const logs = ref([])
const live = ref(true)
const displayTimezone = ref('Asia/Shanghai')
let lastId = 0
let timer = null

const warnCount = computed(() => logs.value.filter((l) => levelClass(l.level) === 'warn').length)
const errorCount = computed(() => logs.value.filter((l) => levelClass(l.level) === 'error').length)
const lastLogTime = computed(() => logs.value.length ? fmt(logs.value[logs.value.length - 1].created_at) : '')

function levelClass(level) {
  const text = String(level || '').toLowerCase()
  if (text.includes('error') || text.includes('fail')) return 'error'
  if (text.includes('warn')) return 'warn'
  return 'info'
}
function fmt(s) { return formatTimeInZone(s, displayTimezone.value) }

async function initial() {
  const [logRes, infoRes] = await Promise.all([
    api.get('/api/logs', { params: { limit: 100 } }),
    api.get('/api/system/info').catch(() => null)
  ])
  logs.value = logRes.data
  lastId = logRes.data.length ? logRes.data[logRes.data.length - 1].id : 0
  if (infoRes?.data?.timezone) displayTimezone.value = infoRes.data.timezone
}

async function poll() {
  if (!live.value) return
  try {
    const { data } = await api.get('/api/logs', { params: { after: lastId } })
    if (data.length) {
      logs.value.push(...data)
      lastId = data[data.length - 1].id
      if (logs.value.length > 400) logs.value.splice(0, logs.value.length - 400)
    }
  } catch { /* ignore transient errors */ }
}

watch(live, (v) => { if (v) poll() })

onMounted(async () => {
  await initial()
  timer = setInterval(poll, 4000)
})
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.logs-page { display: flex; flex-direction: column; gap: 16px; }
.logs-hero { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 18px; align-items: start;
  background: linear-gradient(135deg, color-mix(in srgb, var(--surface) 88%, var(--radar-panel)), var(--surface)); }
.logs-hero > * { position: relative; z-index: 1; }
.hero-kicker { display: flex; align-items: center; gap: 8px; color: var(--text-soft); font-size: 12px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
h1 { margin: 8px 0; }
.hero-copy p { margin: 0; line-height: 1.7; max-width: 660px; }
.switch { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; font-size: 13px; color: var(--text-soft); cursor: pointer; }
.switch input { width: auto; }
.hero-switch { justify-self: end; margin: 0; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--text-soft); }
.dot.on { background: var(--success); box-shadow: 0 0 0 3px color-mix(in srgb, var(--success) 25%, transparent); animation: pulse 1.5s infinite; }
.log-metrics { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 10px; }
.metric-card { padding: 12px; border-radius: 14px; border: 1px solid var(--border); background: color-mix(in srgb, var(--surface-2) 82%, transparent); }
.metric-card span { display: block; color: var(--text-soft); font-size: 12px; margin-bottom: 5px; }
.metric-card b { font-size: 18px; }
.metric-card.warn { border-color: color-mix(in srgb, var(--warning) 30%, var(--border)); }
.metric-card.error { border-color: color-mix(in srgb, var(--danger) 30%, var(--border)); }
.small-value { font-size: 13px !important; }
.terminal-card { padding: 0; overflow: hidden; background: color-mix(in srgb, var(--surface) 88%, #020617); }
.terminal-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 13px 16px; border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--surface-2) 82%, transparent); }
.terminal-title { display: flex; align-items: center; gap: 8px; font-weight: 800; }
.terminal-led { width: 9px; height: 9px; border-radius: 999px; background: var(--text-soft); }
.terminal-led.on { background: var(--success); box-shadow: 0 0 14px color-mix(in srgb, var(--success) 45%, transparent); }
.log-stream { font-family: ui-monospace, "Cascadia Code", Consolas, monospace; font-size: 12.5px; max-height: 70vh; overflow: auto; }
.log-line { display: grid; grid-template-columns: 86px 68px minmax(120px, .8fr) minmax(90px, .6fr) minmax(220px, 1.6fr);
  gap: 10px; padding: 9px 14px; border-bottom: 1px solid var(--border); align-items: baseline; }
.log-line:last-child { border-bottom: none; }
.log-line.warn { background: color-mix(in srgb, var(--warning) 6%, transparent); }
.log-line.error { background: color-mix(in srgb, var(--danger) 7%, transparent); }
.time { color: var(--text-soft); white-space: nowrap; }
.lvl { text-transform: uppercase; font-size: 10px; font-weight: 800; letter-spacing: .04em; padding: 2px 7px; border-radius: 999px; width: fit-content;
  background: color-mix(in srgb, var(--primary) 14%, transparent); color: var(--primary); }
.lvl.warn { background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning); }
.lvl.error { background: color-mix(in srgb, var(--danger) 18%, transparent); color: var(--danger); }
.act { font-weight: 700; word-break: break-word; }
.usr { color: var(--primary); word-break: break-word; }
.detail { color: var(--text-soft); word-break: break-word; line-height: 1.5; }
.empty-log { padding: 18px; }
@keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: .45 } }
@media (prefers-reduced-motion: reduce) {
  .dot.on { animation: none; }
}
@media (max-width: 900px) {
  .logs-hero { grid-template-columns: 1fr; }
  .hero-switch { justify-self: start; }
  .log-metrics { grid-template-columns: 1fr 1fr; }
  .log-line { grid-template-columns: 78px 58px minmax(0, 1fr); }
  .usr, .detail { grid-column: 3 / -1; }
}
@media (max-width: 720px) {
  .log-metrics { grid-template-columns: 1fr; }
  .terminal-head { flex-direction: column; align-items: flex-start; }
  .log-stream { font-size: 12px; max-height: none; }
  .log-line { grid-template-columns: 1fr 1fr; gap: 5px 8px; padding: 10px 12px; }
  .time, .lvl, .act, .usr, .detail { grid-column: auto; }
  .act, .usr, .detail { grid-column: 1 / -1; }
}
</style>
