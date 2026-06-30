<template>
  <div>
    <div class="head">
      <h1>🔔 {{ t('notify.title') }}</h1>
      <button class="btn" @click="runScan">{{ t('notify.runScan') }}</button>
    </div>

    <div class="grid cards">
      <div v-for="l in logs" :key="l.id" class="card log-card" :class="l.status">
        <div class="lc-top">
          <span class="tag" :class="l.status === 'sent' ? 'ok' : 'bad'">
            {{ l.status === 'sent' ? t('notify.sent') : t('notify.failed') }}
          </span>
          <span class="tag chan">{{ l.channel === 'bark' ? '🔔 Bark' : '📲 Telegram' }}</span>
          <span class="muted">{{ fmt(l.sent_at) }}</span>
        </div>
        <div class="lc-body">{{ l.message }}</div>
        <div class="muted sm">{{ t('notify.daysBefore') }}: {{ l.days_before }}</div>
      </div>
      <p v-if="!logs.length" class="muted">{{ t('notify.empty') }}</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'

const { t } = useI18n()
const logs = ref([])

function fmt(s) { return s ? new Date(s).toLocaleString() : '' }

async function load() { logs.value = (await api.get('/api/notifications/logs')).data }
async function runScan() { await api.post('/api/notifications/run-scan'); load() }

onMounted(load)
</script>

<style scoped>
h1 { margin-top: 0; }
.cards { grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); }
.log-card { border-left: 4px solid var(--success); }
.log-card.failed { border-left-color: var(--danger); }
.lc-top { display: flex; justify-content: space-between; align-items: center; font-size: 13px; margin-bottom: 8px; }
.lc-body { font-size: 14px; white-space: pre-wrap; line-height: 1.5; }
.sm { font-size: 12px; margin-top: 8px; }
.tag.ok { background: #dcfce7; color: #15803d; }
.tag.bad { background: #fee2e2; color: #b91c1c; }
.tag.chan { background: var(--surface-2); color: var(--text-soft); }
@media (max-width: 720px) {
  .head { flex-wrap: wrap; gap: 10px; }
  .head .btn { width: 100%; }
  .lc-top { flex-wrap: wrap; gap: 6px; }
}
</style>
