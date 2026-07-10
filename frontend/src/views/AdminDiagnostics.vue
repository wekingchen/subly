<template>
  <div class="diag-page">
    <section class="diag-hero card radar-grid-bg">
      <div class="hero-copy">
        <div class="hero-kicker"><span class="signal-dot"></span>{{ t('diagnostics.kicker') }}</div>
        <h1>{{ t('diagnostics.title') }}</h1>
        <p class="muted">{{ t('diagnostics.subtitle') }}</p>
      </div>
      <div class="hero-actions">
        <button class="btn ghost" :disabled="diagLoading" @click="clickDiagnostics">
          {{ diagLoading ? t('diagnostics.running') : t('diagnostics.run') }}
        </button>
        <button class="btn" :disabled="simLoading" @click="clickSimulation">
          {{ simLoading ? t('diagnostics.simulating') : t('diagnostics.simulate') }}
        </button>
      </div>
      <div class="diag-metrics">
        <div class="metric-card bad"><span>{{ t('diagnostics.errors') }}</span><b class="mono-data">{{ diagnostic.summary?.errors || 0 }}</b></div>
        <div class="metric-card warn"><span>{{ t('diagnostics.warnings') }}</span><b class="mono-data">{{ diagnostic.summary?.warnings || 0 }}</b></div>
        <div class="metric-card"><span>{{ t('diagnostics.infos') }}</span><b class="mono-data">{{ diagnostic.summary?.infos || 0 }}</b></div>
        <div class="metric-card ok"><span>{{ t('diagnostics.wouldSend') }}</span><b class="mono-data">{{ simulation.summary?.would_send || 0 }}</b></div>
      </div>
    </section>

    <section class="card panel-card">
      <div class="panel-head">
        <div>
          <div class="panel-title">{{ t('diagnostics.issueTitle') }}</div>
          <p class="muted">{{ t('diagnostics.issueTip') }}</p>
          <p v-if="diagRunAt" class="muted run-stamp">{{ t('diagnostics.lastRun', { time: diagRunAt }) }}</p>
        </div>
        <div class="seg">
          <button :class="{ active: issueFilter === 'all' }" @click="issueFilter = 'all'">{{ t('diagnostics.all') }}</button>
          <button :class="{ active: issueFilter === 'error' }" @click="issueFilter = 'error'">{{ t('diagnostics.errors') }}</button>
          <button :class="{ active: issueFilter === 'warn' }" @click="issueFilter = 'warn'">{{ t('diagnostics.warnings') }}</button>
          <button :class="{ active: issueFilter === 'info' }" @click="issueFilter = 'info'">{{ t('diagnostics.infos') }}</button>
          <button :class="{ active: issueFilter === 'reminder' }" @click="issueFilter = 'reminder'">{{ t('diagnostics.reminders') }}</button>
        </div>
      </div>

      <p v-if="diagErr" class="err" role="alert">{{ diagErr }}</p>
      <p v-if="diagLoading" class="muted loading-line">{{ t('diagnostics.runningHint') }}</p>
      <div v-else-if="filteredIssues.length" class="issue-list">
        <article v-for="issue in filteredIssues" :key="issueKey(issue)" class="issue-card" :class="severityClass(issue.severity)">
          <div class="issue-top">
            <span class="tag" :class="severityClass(issue.severity)">{{ severityLabel(issue.severity) }}</span>
            <span class="tag scope">{{ issue.scope }}</span>
            <span class="muted mono-data">{{ issue.code }}</span>
          </div>
          <h3>{{ issue.title }}</h3>
          <p>{{ issue.detail }}</p>
          <p class="muted suggestion">{{ issue.suggestion }}</p>
          <div class="issue-foot muted">
            <span v-if="issue.username">{{ issue.username }}</span>
            <span v-if="issue.subscription_name">{{ issue.subscription_name }}</span>
            <span v-if="issue.subscription_id" class="mono-data">#{{ issue.subscription_id }}</span>
          </div>
          <div v-if="isFixable(issue)" class="issue-actions">
            <button class="btn sm" :disabled="repairingKey === issueKey(issue)" @click="clickRepair(issue)">
              {{ repairingKey === issueKey(issue) ? t('diagnostics.repairing') : t('diagnostics.repair') }}
            </button>
            <span v-if="repairErr[issueKey(issue)]" class="err">{{ repairErr[issueKey(issue)] }}</span>
            <span v-else-if="repairOkKey === issueKey(issue)" class="ok-hint">{{ t('diagnostics.repairOk') }}</span>
          </div>
        </article>
      </div>
      <div v-else-if="diagLoaded" class="empty-state"><span class="signal-dot"></span><b>{{ t('diagnostics.noIssues') }}</b></div>
    </section>

    <section class="card panel-card">
      <div class="panel-head">
        <div>
          <div class="panel-title">{{ t('diagnostics.simTitle') }}</div>
          <p class="muted">{{ t('diagnostics.dryRunTip') }}</p>
        </div>
      </div>

      <div class="form-grid sim-form">
        <label>{{ t('diagnostics.asOfDate') }}<input v-model="simForm.as_of_date" type="date" :disabled="simLoading" /></label>
        <label>{{ t('diagnostics.userId') }}<input v-model.number="simForm.user_id" type="number" min="1" placeholder="—" :disabled="simLoading" /></label>
        <label>{{ t('diagnostics.subscriptionId') }}<input v-model.number="simForm.subscription_id" type="number" min="1" placeholder="—" :disabled="simLoading" /></label>
        <label>{{ t('diagnostics.channel') }}
          <select v-model="simForm.channel" :disabled="simLoading">
            <option value="all">{{ t('diagnostics.allChannels') }}</option>
            <option value="telegram">Telegram</option>
            <option value="bark">Bark</option>
          </select>
        </label>
        <label>{{ t('diagnostics.limit') }}<input v-model.number="simForm.limit" type="number" min="1" max="1000" :disabled="simLoading" /></label>
        <label class="check-row"><input v-model="simForm.include_skipped" type="checkbox" :disabled="simLoading" /> {{ t('diagnostics.includeSkipped') }}</label>
      </div>
      <div class="actions-row">
        <button class="btn" :disabled="simLoading" @click="clickSimulation">
          {{ simLoading ? t('diagnostics.simulating') : t('diagnostics.runSimulation') }}
        </button>
        <span v-if="simRunAt" class="muted run-stamp">{{ t('diagnostics.lastRun', { time: simRunAt }) }}</span>
      </div>

      <div class="sim-metrics">
        <span>{{ t('diagnostics.scanned') }} <b class="mono-data">{{ simulation.summary?.scanned || 0 }}</b></span>
        <span>{{ t('diagnostics.wouldSend') }} <b class="mono-data">{{ simulation.summary?.would_send || 0 }}</b></span>
        <span>{{ t('diagnostics.skipped') }} <b class="mono-data">{{ simulation.summary?.skipped || 0 }}</b></span>
        <span>Telegram <b class="mono-data">{{ simulation.summary?.telegram || 0 }}</b></span>
        <span>Bark <b class="mono-data">{{ simulation.summary?.bark || 0 }}</b></span>
      </div>

      <p v-if="simErr" class="err" role="alert">{{ simErr }}</p>
      <p v-if="simLoading" class="muted loading-line">{{ t('diagnostics.simulatingHint') }}</p>
      <div v-else-if="sortedSimulation.length" class="sim-list">
        <article v-for="item in sortedSimulation" :key="simKey(item)" class="sim-card">
          <div class="sim-top">
            <span class="tag" :class="simulationStatusClass(item.status)">{{ simulationStatusLabel(item.status) }}</span>
            <span class="tag chan">{{ channelLabel(item.channel) }}</span>
            <span v-if="item.is_keepalive" class="tag keepalive">{{ t('sub.keepalive.label') }}</span>
          </div>
          <h3>{{ item.subscription_name }}</h3>
          <div class="sim-meta muted">
            <span>{{ item.username }}</span>
            <span v-if="item.next_renewal_date" class="mono-data">{{ item.next_renewal_date }}</span>
            <span v-if="item.days_left !== null" class="mono-data">{{ item.days_left }} 天</span>
          </div>
          <p class="reason">{{ item.reason }}</p>
          <pre v-if="item.preview" class="preview">{{ item.preview }}</pre>
        </article>
      </div>
      <div v-else-if="simLoaded" class="empty-state"><span class="signal-dot"></span><b>{{ t('diagnostics.noSimulation') }}</b></div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import { toISODate } from '../utils/date'
import {
  channelLabel,
  filterIssues,
  isFixable,
  severityClass,
  severityLabel,
  simulationStatusClass,
  simulationStatusLabel,
  sortSimulationItems
} from '../utils/diagnostics'

const { t } = useI18n()
const diagnostic = ref({ summary: {}, issues: [] })
const simulation = ref({ summary: {}, items: [] })
const issueFilter = ref('all')
const diagErr = ref('')
const simErr = ref('')
const repairingKey = ref('')        // per-issue 修复 loading（复用 issueKey）
const repairErr = reactive({})      // { [issueKey]: 错误文案 }
const repairOkKey = ref('')         // 最近修复成功的 key
const diagLoading = ref(true)
const simLoading = ref(true)
const diagLoaded = ref(false)
const simLoaded = ref(false)
const diagRunAt = ref('')
const simRunAt = ref('')
const today = toISODate(new Date())
const simForm = reactive({
  as_of_date: today,
  user_id: null,
  subscription_id: null,
  channel: 'all',
  include_skipped: true,
  limit: 200
})

const filteredIssues = computed(() => filterIssues(diagnostic.value.issues || [], issueFilter.value))
const sortedSimulation = computed(() => sortSimulationItems(simulation.value.items || []))

function cleanPayload() {
  return {
    as_of_date: simForm.as_of_date || null,
    user_id: simForm.user_id || null,
    subscription_id: simForm.subscription_id || null,
    channel: simForm.channel,
    include_skipped: simForm.include_skipped,
    limit: simForm.limit || 200
  }
}

function issueKey(issue) {
  return [issue.severity, issue.scope, issue.code, issue.user_id, issue.subscription_id, issue.detail].join(':')
}
function simKey(item) {
  return [item.subscription_id, item.channel, item.status, item.days_before, item.days_left].join(':')
}

async function loadDiagnostics() {
  diagErr.value = ''
  diagLoading.value = true
  diagLoaded.value = false
  diagnostic.value = { summary: {}, issues: [] }
  try {
    diagnostic.value = (await api.get('/api/admin/diagnostics')).data
    diagRunAt.value = new Date().toLocaleTimeString()
    diagLoaded.value = true
  } catch (e) {
    diagErr.value = e.response?.data?.detail || '诊断失败'
  } finally {
    diagLoading.value = false
  }
}

async function runSimulation() {
  simErr.value = ''
  simLoading.value = true
  simLoaded.value = false
  simulation.value = { summary: {}, items: [] }
  try {
    simulation.value = (await api.post('/api/admin/diagnostics/reminders/simulate', cleanPayload())).data
    simRunAt.value = new Date().toLocaleTimeString()
    simLoaded.value = true
  } catch (e) {
    simErr.value = e.response?.data?.detail || '提醒模拟失败'
  } finally {
    simLoading.value = false
  }
}

// 手动点击时重入保护，避免并发请求复用同一 loading 导致提前复位与结果覆盖
function clickDiagnostics() { if (diagLoading.value) return; loadDiagnostics() }
function clickSimulation() { if (simLoading.value) return; runSimulation() }

async function repairIssue(issue) {
  const key = issueKey(issue)
  repairingKey.value = key
  repairErr[key] = ''
  repairOkKey.value = ''
  // 第一步：提交修复（写操作）。成功后单独保留成功态，不被后续刷新失败覆盖。
  let repaired = false
  try {
    await api.post('/api/admin/diagnostics/repair', { subscription_id: issue.subscription_id, code: issue.code })
    repaired = true
    repairOkKey.value = key
  } catch (e) {
    repairErr[key] = e.response?.status === 409 ? '问题已不存在' : (e.response?.data?.detail || '修复失败')
  } finally {
    repairingKey.value = ''
  }
  // 第二步：刷新诊断列表（读操作）。失败时单独提示，不误报成「修复失败」。
  if (repaired || repairErr[key] === '问题已不存在') {
    try {
      await loadDiagnostics()
    } catch {
      repairErr[key] = repaired ? '已修复，但刷新列表失败，请手动刷新' : repairErr[key]
      repairOkKey.value = repaired ? key : ''
    }
  }
}
function clickRepair(issue) { if (repairingKey.value) return; repairIssue(issue) }

onMounted(() => {
  loadDiagnostics()
  runSimulation()
})
</script>

<style scoped>
.diag-page { display: flex; flex-direction: column; gap: 16px; }
.diag-hero { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 18px; align-items: start;
  background: linear-gradient(135deg, color-mix(in srgb, var(--surface) 88%, var(--radar-panel)), var(--surface)); }
.diag-hero > * { position: relative; z-index: 1; }
.hero-kicker { display: flex; align-items: center; gap: 8px; color: var(--text-soft); font-size: 12px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
h1 { margin: 8px 0; }
.hero-copy p { margin: 0; line-height: 1.7; max-width: 680px; }
.hero-actions { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.diag-metrics { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 10px; }
.metric-card { padding: 12px; border-radius: 14px; border: 1px solid var(--border); background: color-mix(in srgb, var(--surface-2) 82%, transparent); }
.metric-card span { display: block; font-size: 12px; color: var(--text-soft); margin-bottom: 5px; }
.metric-card b { font-size: 20px; }
.metric-card.ok { border-color: color-mix(in srgb, var(--success) 30%, var(--border)); }
.metric-card.warn { border-color: color-mix(in srgb, var(--warning) 30%, var(--border)); }
.metric-card.bad { border-color: color-mix(in srgb, var(--danger) 30%, var(--border)); }
.err { color: var(--danger); }
.loading-line { display: flex; align-items: center; gap: 8px; }
.loading-line::before { content: ''; width: 8px; height: 8px; border-radius: 999px; background: var(--primary); box-shadow: 0 0 12px color-mix(in srgb, var(--primary) 55%, transparent); animation: diag-pulse 1s ease-in-out infinite; }
.run-stamp { margin-top: 4px; font-size: 12px; }
@keyframes diag-pulse { 0%,100% { opacity: .35; } 50% { opacity: 1; } }
.panel-card { display: grid; gap: 14px; }
.panel-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.panel-title { font-weight: 800; font-size: 18px; }
.panel-head p { margin: 4px 0 0; line-height: 1.6; }
.seg { display: flex; flex-wrap: wrap; gap: 6px; }
.seg button { border: 1px solid var(--border); background: var(--surface-2); color: var(--text-soft); border-radius: 999px; padding: 6px 10px; cursor: pointer; }
.seg button.active { color: var(--primary); border-color: color-mix(in srgb, var(--primary) 36%, var(--border)); background: var(--primary-soft); }
.issue-list, .sim-list { display: grid; gap: 10px; }
.issue-card, .sim-card { border: 1px solid var(--border); background: color-mix(in srgb, var(--surface-2) 66%, transparent); border-radius: 14px; padding: 12px; }
.issue-card.bad { border-left: 4px solid var(--danger); }
.issue-card.warn { border-left: 4px solid var(--warning); }
.issue-card.info { border-left: 4px solid var(--primary); }
.issue-top, .sim-top, .issue-foot, .sim-meta { display: flex; flex-wrap: wrap; gap: 7px; align-items: center; }
.issue-card h3, .sim-card h3 { margin: 8px 0 6px; font-size: 15px; }
.issue-card p, .sim-card p { margin: 0; line-height: 1.6; }
.suggestion { margin-top: 6px !important; }
.issue-foot { margin-top: 10px; font-size: 12px; }
.tag.bad { background: color-mix(in srgb, var(--danger) 18%, transparent); color: var(--danger); }
.tag.warn { background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning); }
.tag.info, .tag.muted { background: var(--surface-2); color: var(--text-soft); }
.tag.ok { background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success); }
.tag.scope, .tag.chan { background: var(--surface-2); color: var(--text-soft); }
.tag.keepalive { background: color-mix(in srgb, var(--signal-cyan) 16%, transparent); color: var(--signal-cyan); }
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
.form-grid label { display: grid; gap: 5px; color: var(--text-soft); font-size: 12px; }
.form-grid input, .form-grid select { width: 100%; }
.check-row { align-content: end; grid-template-columns: auto 1fr !important; align-items: center; color: var(--text) !important; }
.check-row input { width: auto; }
.actions-row { display: flex; justify-content: flex-end; }
.sim-metrics { display: flex; flex-wrap: wrap; gap: 8px; color: var(--text-soft); font-size: 13px; }
.sim-metrics span { border: 1px solid var(--border); background: var(--surface-2); border-radius: 999px; padding: 5px 9px; }
.reason { margin-top: 8px !important; }
.preview { margin: 10px 0 0; padding: 10px; border-radius: 10px; border: 1px solid var(--border); background: color-mix(in srgb, var(--surface) 76%, #000 8%); color: var(--text); white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; line-height: 1.5; }
.empty-state { display: flex; align-items: center; gap: 10px; color: var(--text-soft); }
@media (max-width: 720px) {
  .diag-hero { grid-template-columns: 1fr; }
  .hero-actions .btn { flex: 1; }
  .diag-metrics { grid-template-columns: 1fr 1fr; }
  .panel-head { flex-direction: column; }
  .seg { width: 100%; }
}
@media (max-width: 460px) {
  .diag-metrics { grid-template-columns: 1fr; }
}
</style>
