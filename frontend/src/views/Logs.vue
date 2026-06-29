<template>
  <div>
    <div class="head">
      <h1>📜 {{ t('rtlog.title') }}</h1>
      <label class="switch">
        <input type="checkbox" v-model="live" />
        <span class="dot" :class="{ on: live }"></span>
        {{ live ? t('rtlog.live') : t('rtlog.paused') }}
      </label>
    </div>

    <div class="card">
      <div class="log-stream">
        <div v-for="l in logs" :key="l.id" class="log-line" :class="l.level">
          <span class="time">{{ fmt(l.created_at) }}</span>
          <span class="lvl" :class="l.level">{{ l.level }}</span>
          <span class="act">{{ l.action }}</span>
          <span v-if="l.user" class="usr">@{{ l.user }}</span>
          <span class="detail">{{ l.detail }}</span>
        </div>
        <p v-if="!logs.length" class="muted">{{ t('rtlog.empty') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'

const { t } = useI18n()
const logs = ref([])
const live = ref(true)
let lastId = 0
let timer = null

function fmt(s) { return s ? new Date(s).toLocaleTimeString() : '' }

async function initial() {
  const { data } = await api.get('/api/logs', { params: { limit: 100 } })
  logs.value = data
  lastId = data.length ? data[data.length - 1].id : 0
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
.head { display: flex; justify-content: space-between; align-items: center; }
h1 { margin-top: 0; }
.switch { display: flex; align-items: center; gap: 8px; min-height: 44px; font-size: 13px; color: var(--text-soft); cursor: pointer; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--text-soft); }
.dot.on { background: var(--success); box-shadow: 0 0 0 3px rgba(16,185,129,.25); animation: pulse 1.5s infinite; }
@keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: .4 } }
.log-stream { font-family: ui-monospace, "Cascadia Code", Consolas, monospace; font-size: 12.5px;
  max-height: 70vh; overflow: auto; }
.log-line { display: flex; gap: 10px; padding: 6px 4px; border-bottom: 1px solid var(--border); align-items: baseline; }
.time { color: var(--text-soft); white-space: nowrap; }
.lvl { text-transform: uppercase; font-size: 10px; padding: 1px 6px; border-radius: 4px; background: var(--primary-soft); color: var(--primary); }
.lvl.warn { background: #fef3c7; color: #b45309; }
.lvl.error { background: #fee2e2; color: #b91c1c; }
.act { font-weight: 600; white-space: nowrap; }
.usr { color: var(--primary); white-space: nowrap; }
.detail { color: var(--text-soft); word-break: break-word; }

/* 手机端：每条日志换行排版，详情独占一行，避免横向溢出错乱 */
@media (max-width: 720px) {
  .head { flex-wrap: wrap; gap: 8px; }
  .log-stream { font-size: 12px; max-height: none; }
  .log-line { flex-wrap: wrap; gap: 4px 8px; padding: 8px 2px; }
  .detail { flex-basis: 100%; width: 100%; }
}
</style>
