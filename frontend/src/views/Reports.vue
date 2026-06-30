<template>
  <div>
    <h1>{{ t('reports.title') }}</h1>
    <div class="seg">
      <button v-for="tab in tabs" :key="tab" :class="{ on: active === tab }" @click="active = tab">
        {{ t('reports.' + tab) }}
      </button>
    </div>

    <!-- 总览（图表） -->
    <div v-if="active === 'overview'">
      <div class="grid kpis">
        <div class="card kpi k1">
          <div class="kpi-l">{{ t('reports.monthlyTotal') }}</div>
          <div class="kpi-v">{{ cur }} {{ (insights.monthly_total || 0).toFixed(2) }}</div>
        </div>
        <div class="card kpi k2">
          <div class="kpi-l">{{ t('reports.yearlyTotal') }}</div>
          <div class="kpi-v">{{ cur }} {{ ((insights.monthly_total || 0) * 12).toFixed(2) }}</div>
        </div>
        <div class="card kpi k3">
          <div class="kpi-l">{{ t('reports.recurringSubs') }}</div>
          <div class="kpi-v">{{ recurringCount }}</div>
        </div>
        <div class="card kpi k4">
          <div class="kpi-l">{{ t('reports.permanentTotal') }}</div>
          <div class="kpi-v">{{ cur }} {{ (detail.one_time_total || 0).toFixed(2) }}</div>
        </div>
      </div>

      <div class="grid two">
        <div class="card">
          <h3>{{ t('reports.byCategory') }}</h3>
          <div v-if="segments.length" class="donut-wrap">
            <div class="donut" :style="donutStyle">
              <div class="donut-hole">
                <div class="dh-v">{{ cur }} {{ (insights.monthly_total || 0).toFixed(0) }}</div>
                <div class="dh-l muted">{{ t('reports.monthly') }}</div>
              </div>
            </div>
            <div class="legend">
              <div v-for="(b, i) in insights.breakdown" :key="b.category" class="lg">
                <span class="dot" :style="{ background: color(i) }"></span>
                <span class="lg-n">{{ b.category }}</span>
                <span class="lg-p muted">{{ b.percent }}%</span>
              </div>
            </div>
          </div>
          <p v-else class="muted">{{ t('reports.noData') }}</p>
        </div>

        <div class="card">
          <h3>{{ t('reports.spendTrend') }}</h3>
          <div v-if="insights.breakdown?.length" class="bars">
            <div v-for="(b, i) in insights.breakdown" :key="b.category" class="bar-row">
              <div class="bar-label" :title="b.category">{{ b.category }}</div>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: barW(b) + '%', background: color(i) }"></div>
              </div>
              <div class="bar-val">{{ cur }} {{ b.monthly.toFixed(2) }}</div>
            </div>
          </div>
          <p v-else class="muted">{{ t('reports.empty') }}</p>
        </div>
      </div>
    </div>

    <!-- 支出洞察 -->
    <div v-else-if="active === 'insights'">
      <div class="card sect">
        <h3>🏆 {{ t('reports.ranking') }}</h3>
        <div class="tbl-wrap desktop-only">
          <table>
            <thead><tr><th>#</th><th>{{ t('sub.name') }}</th><th>{{ t('reports.category') }}</th><th>{{ t('reports.monthly') }}</th></tr></thead>
            <tbody>
              <tr v-for="(s, i) in ranking" :key="s.id">
                <td class="rk">{{ i + 1 }}</td>
                <td><span class="nm"><ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="nm-ico" /><span class="nm-txt"><b>{{ s.name }}</b><i v-if="s.plan" class="nm-sub">{{ s.plan }}</i><i v-if="s.remark" class="nm-remark">📝 {{ s.remark }}</i></span></span></td>
                <td class="muted">{{ catName(s.category_id) }}</td>
                <td>{{ cur }} {{ (s.amount_in_base || 0).toFixed(2) }}</td>
              </tr>
              <tr v-if="!ranking.length"><td colspan="4" class="muted">{{ t('reports.empty') }}</td></tr>
            </tbody>
          </table>
        </div>
        <div class="ledger mobile-only">
          <div v-for="(s, i) in ranking" :key="s.id" class="ld-row">
            <span class="ld-rk">{{ i + 1 }}</span>
            <ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="ld-ico" />
            <div class="ld-main">
              <div class="ld-n">{{ s.name }}</div>
              <div class="muted ld-s">{{ catName(s.category_id) }}</div>
            </div>
            <div class="ld-amt">{{ cur }} {{ (s.amount_in_base || 0).toFixed(2) }}<span class="muted">/ {{ t('reports.monthly') }}</span></div>
          </div>
          <p v-if="!ranking.length" class="muted">{{ t('reports.empty') }}</p>
        </div>
      </div>

      <div class="grid two">
        <div class="card sect">
          <h3>⏰ {{ t('reports.upcoming') }}</h3>
          <div class="tbl-wrap desktop-only">
          <table>
            <tbody>
              <tr v-for="s in upcoming" :key="s.id" class="status-row" :class="statusOf(s)">
                <td><span class="nm"><ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="nm-ico" /><span class="nm-txt"><b>{{ s.name }}</b><i class="nm-sub">{{ s.plan ? s.plan + ' · ' : '' }}{{ catName(s.category_id) }}</i><i v-if="s.remark" class="nm-remark">📝 {{ s.remark }}</i></span></span></td>
                <td class="muted">{{ s.next_renewal_date }}</td>
                <td>{{ s.amount.toFixed(2) }} {{ s.currency }}</td>
              </tr>
              <tr v-if="!upcoming.length"><td colspan="3" class="muted">{{ t('reports.empty') }}</td></tr>
            </tbody>
          </table>
          </div>
          <div class="ledger mobile-only">
            <div v-for="s in upcoming" :key="s.id" class="ld-row" :class="statusOf(s)">
              <ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="ld-ico" />
              <div class="ld-main">
                <div class="ld-n">{{ s.name }}</div>
                <div class="muted ld-s">{{ s.next_renewal_date }}</div>
              </div>
              <div class="ld-amt">{{ s.amount.toFixed(2) }} {{ s.currency }}</div>
            </div>
            <p v-if="!upcoming.length" class="muted">{{ t('reports.empty') }}</p>
          </div>
        </div>
        <div class="card sect">
          <h3>⚠️ {{ t('reports.expired') }}</h3>
          <div class="tbl-wrap desktop-only">
          <table>
            <tbody>
              <tr v-for="s in expired" :key="s.id" class="status-row overdue">
                <td><span class="nm"><ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="nm-ico" /><span class="nm-txt"><b>{{ s.name }}</b><i class="nm-sub">{{ s.plan ? s.plan + ' · ' : '' }}{{ catName(s.category_id) }}</i><i v-if="s.remark" class="nm-remark">📝 {{ s.remark }}</i></span></span></td>
                <td class="danger">{{ s.next_renewal_date }}</td>
                <td>{{ s.amount.toFixed(2) }} {{ s.currency }}</td>
              </tr>
              <tr v-if="!expired.length"><td colspan="3" class="muted">{{ t('reports.empty') }}</td></tr>
            </tbody>
          </table>
          </div>
          <div class="ledger mobile-only">
            <div v-for="s in expired" :key="s.id" class="ld-row overdue">
              <ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="ld-ico" />
              <div class="ld-main">
                <div class="ld-n">{{ s.name }}</div>
                <div class="muted ld-s">{{ s.next_renewal_date }}</div>
              </div>
              <div class="ld-amt">{{ s.amount.toFixed(2) }} {{ s.currency }}</div>
            </div>
            <p v-if="!expired.length" class="muted">{{ t('reports.empty') }}</p>
          </div>
        </div>
      </div>

      <div class="card sect">
        <h3>♾️ {{ t('reports.oneTime') }}</h3>
        <div class="tbl-wrap desktop-only">
        <table>
          <thead><tr><th>{{ t('sub.name') }}</th><th>{{ t('reports.category') }}</th><th>{{ t('sub.amount') }}</th><th>{{ t('sub.startDate') }}</th></tr></thead>
          <tbody>
            <tr v-for="s in oneTime" :key="s.id">
              <td><span class="nm"><ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="nm-ico" /><span class="nm-txt"><b>{{ s.name }}</b><i v-if="s.plan" class="nm-sub">{{ s.plan }}</i><i v-if="s.remark" class="nm-remark">📝 {{ s.remark }}</i></span></span></td>
              <td class="muted">{{ catName(s.category_id) }}</td>
              <td>{{ s.amount.toFixed(2) }} {{ s.currency }}</td>
              <td class="muted">{{ s.start_date }}</td>
            </tr>
            <tr v-if="!oneTime.length"><td colspan="4" class="muted">{{ t('reports.empty') }}</td></tr>
          </tbody>
        </table>
        </div>
        <div class="ledger mobile-only">
          <div v-for="s in oneTime" :key="s.id" class="ld-row oneTime">
            <ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="ld-ico" />
            <div class="ld-main">
              <div class="ld-n">{{ s.name }}</div>
              <div class="muted ld-s">{{ catName(s.category_id) }} · {{ s.start_date }}</div>
            </div>
            <div class="ld-amt">{{ s.amount.toFixed(2) }} {{ s.currency }}</div>
          </div>
          <p v-if="!oneTime.length" class="muted">{{ t('reports.empty') }}</p>
        </div>
      </div>
    </div>

    <!-- 分类明细 -->
    <div v-else-if="active === 'categoryDetail'">
      <div class="grid two">
        <div class="card sect">
          <h3>🔁 {{ t('reports.recurringSubs') }}
            <span class="muted total">{{ cur }} {{ (detail.recurring_monthly_total || 0).toFixed(2) }} / {{ t('reports.monthly') }}</span>
          </h3>
          <div class="tbl-wrap">
          <table>
            <thead><tr><th>{{ t('reports.category') }}</th><th>{{ t('reports.count') }}</th><th>{{ t('reports.monthly') }}</th></tr></thead>
            <tbody>
              <tr v-for="r in detail.recurring" :key="r.category">
                <td>{{ r.category }}</td><td>{{ r.count }}</td><td>{{ cur }} {{ r.monthly.toFixed(2) }}</td>
              </tr>
              <tr v-if="!detail.recurring?.length"><td colspan="3" class="muted">{{ t('reports.empty') }}</td></tr>
            </tbody>
          </table>
          </div>
        </div>
        <div class="card sect">
          <h3>♾️ {{ t('reports.permanentBuy') }}
            <span class="muted total">{{ cur }} {{ (detail.one_time_total || 0).toFixed(2) }}</span>
          </h3>
          <div class="tbl-wrap">
          <table>
            <thead><tr><th>{{ t('reports.category') }}</th><th>{{ t('reports.count') }}</th><th>{{ t('reports.amount') }}</th></tr></thead>
            <tbody>
              <tr v-for="r in detail.one_time" :key="r.category">
                <td>{{ r.category }}</td><td>{{ r.count }}</td><td>{{ cur }} {{ r.total.toFixed(2) }}</td>
              </tr>
              <tr v-if="!detail.one_time?.length"><td colspan="3" class="muted">{{ t('reports.empty') }}</td></tr>
            </tbody>
          </table>
          </div>
        </div>
      </div>
    </div>

    <!-- 近期付款 -->
    <div v-else class="card">
      <h3>💸 {{ t('reports.recentPayments') }}</h3>
      <div v-for="p in payments" :key="p.id + '-' + p.date" class="pay-row">
        <span class="pay-ico">
          <ServiceIcon :src="p.icon" :name="p.name" :fallback="p.icon || '🔖'" class="pay-ico-img" />
        </span>
        <div class="pay-main">
          <div class="pay-n">{{ p.name }}<span v-if="p.plan" class="pay-plan"> · {{ p.plan }}</span></div>
          <div class="muted pay-d">{{ p.date }} · {{ p.category || catName(null) }} · {{ p.billing_type === 'recurring' ? t('sub.recurring') : t('sub.oneTime') }}</div>
          <div v-if="p.remark" class="pay-d pay-remark">📝 {{ p.remark }}</div>
        </div>
        <div class="pay-amt">{{ p.amount.toFixed(2) }} {{ p.currency }}</div>
      </div>
      <p v-if="!payments.length" class="muted">{{ t('reports.empty') }}</p>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import ServiceIcon from '../components/ServiceIcon.vue'
import { useAuth } from '../stores/auth'

const { t } = useI18n()
const auth = useAuth()
const tabs = ['overview', 'insights', 'categoryDetail', 'recentPayments']
const active = ref('overview')
const cur = auth.user?.base_currency || 'CNY'

const insights = ref({ breakdown: [] })
const detail = ref({ recurring: [], one_time: [] })
const ranking = ref([])
const oneTime = ref([])
const upcoming = ref([])
const expired = ref([])
const payments = ref([])
const cats = ref([])

function catName(id) {
  if (id == null) return t('sub.uncategorized')
  const c = cats.value.find((x) => x.id === id)
  return c ? c.name : t('sub.uncategorized')
}
function emojiOf(s) { return s.icon && !isImg(s.icon) ? s.icon : '🔖' }

const PALETTE = ['#5b5bd6', '#06b6d4', '#16a34a', '#f59e0b', '#ef4444', '#a855f7', '#0ea5e9', '#ec4899', '#14b8a6', '#f97316', '#8b5cf6', '#22c55e']
function color(i) { return PALETTE[i % PALETTE.length] }
function isImg(v) { return typeof v === 'string' && (v.startsWith('/') || v.startsWith('http')) }
function daysLeft(s) {
  if (!s.next_renewal_date) return null
  return Math.ceil((new Date(s.next_renewal_date) - new Date()) / 86400000)
}
function statusOf(s) {
  const d = daysLeft(s)
  if (d === null) return 'ok'
  if (d < 0) return 'overdue'
  if (d <= 7) return 'soon'
  return 'ok'
}

const segments = computed(() => (insights.value.breakdown || []).filter((b) => b.percent > 0))
const donutStyle = computed(() => {
  const bd = insights.value.breakdown || []
  if (!bd.length) return { background: 'var(--border)' }
  let acc = 0
  const stops = []
  bd.forEach((b, i) => {
    const start = acc
    acc += b.percent
    stops.push(`${color(i)} ${start}% ${acc}%`)
  })
  if (acc < 100) stops.push(`var(--border) ${acc}% 100%`)
  return { background: `conic-gradient(${stops.join(',')})` }
})
const maxMonthly = computed(() => Math.max(1, ...(insights.value.breakdown || []).map((b) => b.monthly)))
function barW(b) { return Math.round((b.monthly / maxMonthly.value) * 100) }
const recurringCount = computed(() => (detail.value.recurring || []).reduce((a, r) => a + r.count, 0))

async function loadOverview() {
  const [ins, det] = await Promise.all([
    api.get('/api/reports/insights'),
    api.get('/api/reports/category-detail')
  ])
  insights.value = ins.data
  detail.value = det.data
}
async function loadInsights() {
  const [r, o, u, e] = await Promise.all([
    api.get('/api/reports/ranking'),
    api.get('/api/reports/one-time'),
    api.get('/api/reports/upcoming'),
    api.get('/api/reports/expired')
  ])
  ranking.value = r.data; oneTime.value = o.data; upcoming.value = u.data; expired.value = e.data
}
async function loadDetail() { detail.value = (await api.get('/api/reports/category-detail')).data }
async function loadPayments() { payments.value = (await api.get('/api/reports/recent-payments')).data.items }

function loadActive() {
  if (active.value === 'overview') loadOverview()
  else if (active.value === 'insights') loadInsights()
  else if (active.value === 'categoryDetail') loadDetail()
  else loadPayments()
}

watch(active, loadActive)
onMounted(async () => {
  cats.value = (await api.get('/api/categories').catch(() => ({ data: [] }))).data || []
  loadActive()
})
</script>

<style scoped>
h1 { margin-top: 0; }
.seg { margin-bottom: 14px; }
.seg button { white-space: nowrap; }
.two { grid-template-columns: 1fr 1fr; }
.sect { margin-bottom: 16px; }
.sect h3 { margin-top: 0; display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.total { font-size: 13px; font-weight: 500; }
.danger { color: var(--danger); }
.status-row { position: relative; }
.status-row td:first-child { border-left: 3px solid transparent; }
.status-row.soon td:first-child { border-left-color: var(--warning); }
.status-row.overdue td:first-child { border-left-color: var(--danger); }
.status-row.ok td:first-child { border-left-color: color-mix(in srgb, var(--success) 55%, transparent); }

.mobile-only { display: none; }
.rk { width: 28px; color: var(--text-soft); font-weight: 600; }
.nm { display: flex; align-items: center; gap: 9px; min-width: 0; }
.nm-ico { width: 26px; height: 26px; border-radius: 7px; object-fit: contain; flex-shrink: 0;
  border: 1px solid var(--border); background: var(--surface-2); }
.nm-emoji { width: 26px; height: 26px; display: inline-flex; align-items: center; justify-content: center;
  font-size: 17px; flex-shrink: 0; border-radius: 7px; background: var(--surface-2); border: 1px solid var(--border); }
.nm-txt { display: flex; flex-direction: column; min-width: 0; line-height: 1.25; }
.nm-txt b { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-sub { font-size: 12px; color: var(--text-soft); font-style: normal; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm-remark { font-size: 12px; color: var(--primary); font-style: normal; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 220px; }
.pay-plan { font-weight: 500; color: var(--text-soft); font-size: 13px; }
.pay-remark { color: var(--primary); }

/* KPI */
.kpis { grid-template-columns: repeat(4, 1fr); margin-bottom: 16px; }
.kpi { position: relative; overflow: hidden; }
.kpi-l { font-size: 13px; color: var(--text-soft); }
.kpi-v { font-size: 23px; font-weight: 700; margin-top: 6px; letter-spacing: -.02em; }
.kpi::after { content: ''; position: absolute; right: -20px; top: -20px; width: 70px; height: 70px;
  border-radius: 50%; opacity: .15; }
.k1::after { background: var(--primary); }
.k2::after { background: #06b6d4; }
.k3::after { background: #16a34a; }
.k4::after { background: #f59e0b; }

/* 环形图 */
.donut-wrap { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
.donut { width: 150px; height: 150px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; }
.donut-hole { width: 96px; height: 96px; border-radius: 50%; background: var(--surface);
  display: flex; flex-direction: column; align-items: center; justify-content: center; }
.dh-v { font-size: 17px; font-weight: 700; }
.dh-l { font-size: 11px; }
.legend { flex: 1; min-width: 140px; display: flex; flex-direction: column; gap: 6px; }
.lg { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
.lg-n { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* 柱状 */
.bar-row { display: grid; grid-template-columns: 130px 1fr 110px; align-items: center; gap: 10px; margin: 9px 0; }
.bar-label { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-track { background: var(--bg); border-radius: 20px; height: 12px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 20px; transition: width .4s ease; }
.bar-val { font-size: 13px; color: var(--text-soft); text-align: right; }

/* 近期付款 */
.pay-row { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.pay-row:last-child { border-bottom: none; }
.pay-ico { width: 34px; height: 34px; border-radius: 9px; background: var(--surface-2); border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
.pay-ico-img { width: 22px; height: 22px; border-radius: 6px; object-fit: contain; }
.pay-main { flex: 1; min-width: 0; }
.pay-n { font-weight: 600; font-size: 14px; }
.pay-d { font-size: 12px; }
.pay-amt { font-weight: 600; font-size: 14px; }

/* 移动端账本列表（默认隐藏，仅移动端显示；desktop 表格同理仅移动端隐藏）*/
.ledger { display: none; flex-direction: column; }
.ld-row { display: flex; align-items: center; gap: 10px; padding: 11px 4px; border-bottom: 1px solid var(--border);
  min-height: 44px; border-left: 3px solid transparent; padding-left: 8px; }
.ld-row:last-child { border-bottom: none; }
.ld-row.soon { border-left-color: var(--warning); }
.ld-row.overdue { border-left-color: var(--danger); }
.ld-row.ok { border-left-color: color-mix(in srgb, var(--success) 55%, transparent); }
.ld-row.oneTime { border-left-color: color-mix(in srgb, var(--text-soft) 40%, transparent); }
.ld-rk { width: 22px; height: 22px; flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center;
  border-radius: 999px; background: var(--surface-2); color: var(--text-soft); font-size: 12px; font-weight: 700; }
.ld-ico { width: 26px; height: 26px; border-radius: 7px; object-fit: contain; flex-shrink: 0;
  border: 1px solid var(--border); background: var(--surface-2); }
.ld-main { flex: 1; min-width: 0; }
.ld-n { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ld-s { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ld-amt { font-weight: 600; font-size: 14px; text-align: right; white-space: nowrap; }
.ld-amt .muted { font-size: 11px; font-weight: 500; }

@media (max-width: 720px) {
  .kpis { grid-template-columns: 1fr 1fr; }
  .kpi-v { font-size: 20px; }
  .two { grid-template-columns: 1fr; }
  .desktop-only { display: none; }
  .mobile-only { display: flex; }
}
@media (max-width: 480px) {
  .bar-row { grid-template-columns: 1fr auto; gap: 6px; }
  .bar-track { grid-column: 1 / -1; }
  .bar-val { text-align: right; }
}
</style>

