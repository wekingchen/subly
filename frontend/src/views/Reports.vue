<template>
  <div>
    <h1 class="sr-only" tabindex="-1">{{ t('reports.title') }}</h1>
    <DataState
      v-if="dataState !== 'ready'"
      :state="dataState"
      :trust="dataState === 'stale' ? 'stale' : 'unknown'"
      :compact="dataState === 'refreshing' || dataState === 'stale'"
      error-title="支出报表加载失败"
      stale-title="刷新失败，当前显示上次加载的报表"
      @retry="loadActive"
    />
    <template v-if="hasLoaded">
    <p v-if="financeCompleteness?.is_complete === false" class="finance-warning" role="status">
      {{ t('reports.incompleteFx', { currencies: (financeCompleteness.missing_currencies || []).join('、') }) }}
    </p>
    <div class="report-head card radar-grid-bg" :class="reportStatus">
      <div class="report-title">
        <div class="hero-kicker">
          <SignalDot :status="reportStatus" />{{ t('reports.finRadar') }}
        </div>
        <div class="report-heading">{{ t('reports.title') }}</div>
        <p class="muted">{{ t('reports.reportSubtitle') }}</p>
      </div>
      <div class="report-head-metrics">
        <div class="head-metric">
          <span>{{ t('reports.monthlyTotal') }}</span>
          <strong class="mono-data">{{ money(insights.monthly_total || 0) }}</strong>
        </div>
        <div class="head-metric">
          <span>{{ t('reports.recurringSubs') }}</span>
          <strong class="mono-data">{{ recurringCount }}</strong>
        </div>
      </div>
    </div>

    <div class="seg report-tabs">
      <button v-for="tab in tabs" :key="tab" :class="{ on: active === tab }" @click="active = tab">
        {{ t('reports.' + tab) }}
      </button>
    </div>

    <!-- 总览（图表） -->
    <div v-if="active === 'overview'">
      <div class="grid kpis">
        <div class="card kpi k1">
          <span class="kpi-signal"></span>
          <div class="kpi-l">{{ t('reports.monthlyTotal') }}</div>
          <div class="kpi-v mono-data">{{ money(insights.monthly_total || 0) }}</div>
        </div>
        <div class="card kpi k2">
          <span class="kpi-signal"></span>
          <div class="kpi-l">{{ t('reports.yearlyTotal') }}</div>
          <div class="kpi-v mono-data">{{ money((insights.monthly_total || 0) * 12) }}</div>
        </div>
        <div class="card kpi k3">
          <span class="kpi-signal"></span>
          <div class="kpi-l">{{ t('reports.recurringSubs') }}</div>
          <div class="kpi-v mono-data">{{ recurringCount }}</div>
        </div>
        <div class="card kpi k4">
          <span class="kpi-signal"></span>
          <div class="kpi-l">{{ t('reports.permanentTotal') }}</div>
          <div class="kpi-v mono-data">{{ money(detail.one_time_total || 0) }}</div>
        </div>
      </div>

      <div class="card budget-card" v-if="budget !== null">
        <div class="budget-head">
          <span class="panel-title"><span class="panel-signal"></span>{{ t('reports.budget') }}</span>
          <span class="mono-data" :class="{ over: budgetOver }">
            {{ money(monthlyTotal) }} / {{ money(budget) }}
          </span>
        </div>
        <div class="budget-track">
          <div class="budget-fill" :class="{ over: budgetOver }" :style="{ width: budgetPct + '%' }"></div>
        </div>
        <p class="muted budget-status">
          {{ budgetOver ? t('reports.budgetOver', { n: money(monthlyTotal - budget) })
                        : t('reports.budgetUsed', { n: budgetPct }) }}
        </p>
      </div>

      <div class="card trend-card">
        <div class="trend-card-head">
          <h3 class="panel-title"><span class="panel-signal"></span>{{ t('reports.trend') }}</h3>
          <div class="seg trend-range" role="group" :aria-label="t('reports.trendRange')">
            <button
              v-for="months in trendMonthOptions"
              :key="months"
              type="button"
              :class="{ on: trendMonths === months }"
              :aria-pressed="trendMonths === months"
              @click="setTrendMonths(months)"
            >
              {{ t('reports.trendMonths', { n: months }) }}
            </button>
          </div>
        </div>
        <TrendChart :history="paymentHistory" :future="futureTrend" :base-currency="cur" :current-month="currentMonth" />
        <p v-if="trendError" class="trend-error" role="alert">{{ trendError }}</p>
      </div>

      <div class="grid two">
        <div class="card chart-card">
          <h3 class="panel-title"><span class="panel-signal"></span>{{ t('reports.byCategory') }}</h3>
          <div v-if="segments.length" class="donut-wrap">
            <div class="donut" :style="donutStyle">
              <div class="donut-hole">
                <div class="dh-v mono-data">{{ money(insights.monthly_total || 0, cur, { decimals: 0 }) }}</div>
                <div class="dh-l muted">{{ t('reports.monthly') }}</div>
              </div>
            </div>
            <div class="legend">
              <div v-for="b in insights.breakdown" :key="categoryVisualKey(b)" class="lg">
                <span class="dot" :style="{ background: categoryColor(b) }"></span>
                <span class="lg-n">{{ b.category }}</span>
                <span class="lg-p muted mono-data">{{ b.percent }}%</span>
              </div>
            </div>
          </div>
          <p v-else class="muted">{{ t('reports.noData') }}</p>
        </div>

        <div class="card chart-card">
          <h3 class="panel-title"><span class="panel-signal"></span>{{ t('reports.spendTrend') }}</h3>
          <div v-if="insights.breakdown?.length" class="bars">
            <div v-for="b in insights.breakdown" :key="categoryVisualKey(b)" class="bar-row">
              <div class="bar-label" :title="b.category">{{ b.category }}</div>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: barW(b) + '%', background: categoryColor(b) }"></div>
              </div>
              <div class="bar-val mono-data">{{ money(b.monthly) }}</div>
            </div>
          </div>
          <p v-else class="muted">{{ t('reports.empty') }}</p>
        </div>
      </div>
    </div>

    <!-- 支出洞察 -->
    <div v-else-if="active === 'insights'">
      <div class="card report-radar radar-grid-bg" :class="reportStatus">
        <div class="radar-head">
          <div>
            <div class="hero-kicker"><SignalDot :status="reportStatus" />{{ t('reports.riskRadar') }}</div>
            <h3>{{ t('reports.riskRadar') }}</h3>
          </div>
          <span class="risk-total mono-data muted">{{ t('reports.riskTotal') }} · {{ riskTotal }}</span>
        </div>
        <RadarBars :bars="riskRadarBars" :currency="cur" />
      </div>

      <div class="card sect">
        <h3 class="panel-title"><span class="panel-signal"></span>{{ t('reports.ranking') }}</h3>
        <div v-if="isDesktop" class="tbl-wrap">
          <table>
            <thead><tr><th>#</th><th>{{ t('sub.name') }}</th><th>{{ t('reports.category') }}</th><th>{{ t('reports.monthly') }}</th></tr></thead>
            <tbody>
              <tr v-for="(s, i) in ranking" :key="s.id">
                <td class="rk mono-data">{{ i + 1 }}</td>
                <td><span class="nm"><ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="nm-ico" /><span class="nm-txt"><b>{{ s.name }}</b><i v-if="s.plan" class="nm-sub">{{ s.plan }}</i><i v-if="s.remark" class="nm-remark">📝 {{ s.remark }}</i></span></span></td>
                <td class="muted">{{ catName(s.category_id) }}</td>
                <td class="mono-data money-cell">{{ s.monthly_cost_in_base == null ? t('reports.rateUnavailable') : money(s.monthly_cost_in_base) }}</td>
              </tr>
              <tr v-if="!ranking.length"><td colspan="4" class="muted">{{ t('reports.empty') }}</td></tr>
            </tbody>
          </table>
        </div>
        <div v-else class="ledger">
          <div v-for="(s, i) in ranking" :key="s.id" class="ld-row rank-row">
            <span class="ld-rk mono-data">{{ i + 1 }}</span>
            <ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="ld-ico" />
            <div class="ld-main">
              <div class="ld-n">{{ s.name }}</div>
              <div class="ld-meta">{{ ledgerMeta(s) }}</div>
              <div v-if="cleanText(s.remark)" class="ld-remark">📝 {{ cleanText(s.remark) }}</div>
            </div>
            <div class="ld-amt mono-data">{{ s.monthly_cost_in_base == null ? t('reports.rateUnavailable') : money(s.monthly_cost_in_base) }}<span class="muted">/ {{ t('reports.monthly') }}</span></div>
          </div>
          <p v-if="!ranking.length" class="muted">{{ t('reports.empty') }}</p>
        </div>
      </div>

      <div class="grid two">
        <div class="card sect signal-panel soon-panel">
          <h3 class="panel-title"><span class="panel-signal"></span>{{ t('reports.upcoming') }}</h3>
          <div v-if="isDesktop" class="tbl-wrap">
          <table>
            <tbody>
              <tr v-for="s in upcoming" :key="s.id" class="status-row" :class="statusOf(s)">
                <td><span class="signal-cell"><span class="event-signal"></span><span class="nm"><ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="nm-ico" /><span class="nm-txt"><b>{{ s.name }}</b><i class="nm-sub">{{ s.plan ? s.plan + ' · ' : '' }}{{ catName(s.category_id) }}</i><i v-if="s.remark" class="nm-remark">📝 {{ s.remark }}</i></span></span></span></td>
                <td class="muted mono-data date-cell">{{ s.next_renewal_date }}</td>
                <td class="mono-data money-cell">{{ money(s.amount, s.currency, { position: 'suffix' }) }}</td>
              </tr>
              <tr v-if="!upcoming.length"><td colspan="3" class="muted">{{ t('reports.empty') }}</td></tr>
            </tbody>
          </table>
          </div>
          <div v-else class="ledger">
            <div v-for="s in upcoming" :key="s.id" class="ld-row" :class="statusOf(s)">
              <span class="event-signal"></span>
              <ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="ld-ico" />
              <div class="ld-main">
                <div class="ld-n">{{ s.name }}</div>
                <div class="ld-meta">{{ ledgerMeta(s) }}</div>
                <div v-if="s.next_renewal_date" class="ld-date mono-data">{{ s.next_renewal_date }}</div>
                <div v-if="cleanText(s.remark)" class="ld-remark">📝 {{ cleanText(s.remark) }}</div>
              </div>
              <div class="ld-amt mono-data">{{ money(s.amount, s.currency, { position: 'suffix' }) }}</div>
            </div>
            <p v-if="!upcoming.length" class="muted">{{ t('reports.empty') }}</p>
          </div>
        </div>
        <div class="card sect signal-panel overdue-panel">
          <h3 class="panel-title"><span class="panel-signal"></span>{{ t('reports.expired') }}</h3>
          <div v-if="isDesktop" class="tbl-wrap">
          <table>
            <tbody>
              <tr v-for="s in expired" :key="s.id" class="status-row overdue">
                <td><span class="signal-cell"><span class="event-signal"></span><span class="nm"><ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="nm-ico" /><span class="nm-txt"><b>{{ s.name }}</b><i class="nm-sub">{{ s.plan ? s.plan + ' · ' : '' }}{{ catName(s.category_id) }}</i><i v-if="s.remark" class="nm-remark">📝 {{ s.remark }}</i></span></span></span></td>
                <td class="danger mono-data date-cell">{{ s.next_renewal_date }}</td>
                <td class="mono-data money-cell">{{ money(s.amount, s.currency, { position: 'suffix' }) }}</td>
              </tr>
              <tr v-if="!expired.length"><td colspan="3" class="muted">{{ t('reports.empty') }}</td></tr>
            </tbody>
          </table>
          </div>
          <div v-else class="ledger">
            <div v-for="s in expired" :key="s.id" class="ld-row overdue">
              <span class="event-signal"></span>
              <ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="ld-ico" />
              <div class="ld-main">
                <div class="ld-n">{{ s.name }}</div>
                <div class="ld-meta">{{ ledgerMeta(s) }}</div>
                <div v-if="s.next_renewal_date" class="ld-date mono-data">{{ s.next_renewal_date }}</div>
                <div v-if="cleanText(s.remark)" class="ld-remark">📝 {{ cleanText(s.remark) }}</div>
              </div>
              <div class="ld-amt mono-data">{{ money(s.amount, s.currency, { position: 'suffix' }) }}</div>
            </div>
            <p v-if="!expired.length" class="muted">{{ t('reports.empty') }}</p>
          </div>
        </div>
      </div>

      <div class="card sect signal-panel lifetime-panel">
        <h3 class="panel-title"><span class="panel-signal"></span>{{ t('reports.oneTime') }}</h3>
        <div v-if="isDesktop" class="tbl-wrap">
        <table>
          <thead><tr><th>{{ t('sub.name') }}</th><th>{{ t('reports.category') }}</th><th>{{ t('sub.amount') }}</th><th>{{ t('sub.startDate') }}</th></tr></thead>
          <tbody>
            <tr v-for="s in oneTime" :key="s.id" class="status-row oneTime">
              <td><span class="signal-cell"><span class="event-signal"></span><span class="nm"><ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="nm-ico" /><span class="nm-txt"><b>{{ s.name }}</b><i v-if="s.plan" class="nm-sub">{{ s.plan }}</i><i v-if="s.remark" class="nm-remark">📝 {{ s.remark }}</i></span></span></span></td>
              <td class="muted">{{ catName(s.category_id) }}</td>
              <td class="mono-data money-cell">{{ money(s.amount, s.currency, { position: 'suffix' }) }}</td>
              <td class="muted mono-data date-cell">{{ s.start_date }}</td>
            </tr>
            <tr v-if="!oneTime.length"><td colspan="4" class="muted">{{ t('reports.empty') }}</td></tr>
          </tbody>
        </table>
        </div>
        <div v-else class="ledger">
          <div v-for="s in oneTime" :key="s.id" class="ld-row oneTime">
            <span class="event-signal"></span>
            <ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="ld-ico" />
            <div class="ld-main">
              <div class="ld-n">{{ s.name }}</div>
              <div class="ld-meta">{{ ledgerMeta(s) }}</div>
              <div v-if="s.start_date" class="ld-date mono-data">{{ s.start_date }}</div>
              <div v-if="cleanText(s.remark)" class="ld-remark">📝 {{ cleanText(s.remark) }}</div>
            </div>
            <div class="ld-amt mono-data">{{ money(s.amount, s.currency, { position: 'suffix' }) }}</div>
          </div>
          <p v-if="!oneTime.length" class="muted">{{ t('reports.empty') }}</p>
        </div>
      </div>
    </div>

    <!-- 分类明细 -->
    <div v-else-if="active === 'categoryDetail'">
      <div class="grid two">
        <div class="card sect signal-panel detail-recurring">
          <h3 class="panel-title"><span class="panel-signal"></span>{{ t('reports.recurringSubs') }}
            <span class="muted total mono-data">{{ money(detail.recurring_monthly_total || 0) }} / {{ t('reports.monthly') }}</span>
          </h3>
          <div v-if="isDesktop" class="tbl-wrap">
          <table>
            <thead><tr><th>{{ t('reports.category') }}</th><th>{{ t('reports.count') }}</th><th>{{ t('reports.monthly') }}</th></tr></thead>
            <tbody>
              <tr v-for="r in detail.recurring" :key="categoryVisualKey(r)">
                <td>{{ r.category }}</td><td class="mono-data">{{ r.count }}</td><td class="mono-data money-cell">{{ money(r.monthly) }}</td>
              </tr>
              <tr v-if="!detail.recurring?.length"><td colspan="3" class="muted">{{ t('reports.empty') }}</td></tr>
            </tbody>
          </table>
          </div>
          <div v-else class="ledger">
            <div v-for="r in detail.recurring" :key="categoryVisualKey(r)" class="ld-row">
              <div class="ld-main">
                <div class="ld-n">{{ r.category }}</div>
                <div class="ld-meta">{{ r.count }} {{ t('reports.countUnit') }}</div>
              </div>
              <div class="ld-amt mono-data">{{ money(r.monthly) }}</div>
            </div>
            <p v-if="!detail.recurring?.length" class="muted">{{ t('reports.empty') }}</p>
          </div>
        </div>
        <div class="card sect signal-panel detail-lifetime">
          <h3 class="panel-title"><span class="panel-signal"></span>{{ t('reports.permanentBuy') }}
            <span class="muted total mono-data">{{ money(detail.one_time_total || 0) }}</span>
          </h3>
          <div v-if="isDesktop" class="tbl-wrap">
          <table>
            <thead><tr><th>{{ t('reports.category') }}</th><th>{{ t('reports.count') }}</th><th>{{ t('reports.amount') }}</th></tr></thead>
            <tbody>
              <tr v-for="r in detail.one_time" :key="categoryVisualKey(r)">
                <td>{{ r.category }}</td><td class="mono-data">{{ r.count }}</td><td class="mono-data money-cell">{{ money(r.total) }}</td>
              </tr>
              <tr v-if="!detail.one_time?.length"><td colspan="3" class="muted">{{ t('reports.empty') }}</td></tr>
            </tbody>
          </table>
          </div>
          <div v-else class="ledger">
            <div v-for="r in detail.one_time" :key="categoryVisualKey(r)" class="ld-row">
              <div class="ld-main">
                <div class="ld-n">{{ r.category }}</div>
                <div class="ld-meta">{{ r.count }} {{ t('reports.countUnit') }}</div>
              </div>
              <div class="ld-amt mono-data">{{ money(r.total) }}</div>
            </div>
            <p v-if="!detail.one_time?.length" class="muted">{{ t('reports.empty') }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 近期付款 -->
    <div v-else class="card payments-card">
      <h3 class="panel-title"><span class="panel-signal"></span>{{ t('reports.recentPayments') }}</h3>
      <div v-for="p in payments" :key="p.id + '-' + p.date" class="pay-row" :class="p.billing_type === 'recurring' ? 'recurring' : 'oneTime'">
        <span class="pay-signal"></span>
        <span class="pay-ico">
          <ServiceIcon :src="p.icon" :name="p.name" :fallback="emojiOf(p)" class="pay-ico-img" />
        </span>
        <div class="pay-main">
          <div class="pay-n">{{ p.name }}<span v-if="p.plan" class="pay-plan"> · {{ p.plan }}</span></div>
          <div class="muted pay-d"><span class="mono-data">{{ p.date }}</span> · {{ p.category || catName(null) }} · {{ p.billing_type === 'recurring' ? t('sub.recurring') : t('sub.oneTime') }}</div>
          <div v-if="p.remark" class="pay-d pay-remark">📝 {{ p.remark }}</div>
        </div>
        <div class="pay-amt mono-data">{{ money(p.amount, p.currency, { position: 'suffix' }) }}</div>
      </div>
      <p v-if="!payments.length" class="muted">{{ t('reports.empty') }}</p>
    </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import DataState from '../components/DataState.vue'
import RadarBars from '../components/RadarBars.vue'
import ServiceIcon from '../components/ServiceIcon.vue'
import SignalDot from '../components/SignalDot.vue'
import TrendChart from '../components/TrendChart.vue'
import { useBreakpoint } from '../composables/useBreakpoint'
import { useAuth } from '../stores/auth'
import { categoryColor, categoryVisualKey } from '../utils/categoryVisual'
import { daysLeft } from '../utils/date'
import { createRequestGuard } from '../utils/dataRequest'
import { emojiOf } from '../utils/icon'
import { baseAmountOf, formatMoney } from '../utils/money'
import { renewalStatus } from '../utils/renewal'
import { buildFutureTrend, TREND_MONTH_OPTIONS } from '../utils/trend'

const { t } = useI18n()
const auth = useAuth()
const isDesktop = useBreakpoint('(min-width: 721px)')
const tabs = ['overview', 'insights', 'categoryDetail', 'recentPayments']
const active = ref('overview')
const tabStates = reactive(Object.fromEntries(tabs.map((tab) => [tab, {
  initialLoading: false,
  refreshing: false,
  initialError: false,
  stale: false,
  hasLoaded: false
}])))
const currentTabState = computed(() => tabStates[active.value])
const hasLoaded = computed(() => currentTabState.value.hasLoaded)
const dataState = computed(() => {
  const state = currentTabState.value
  if (state.initialLoading) return 'loading'
  if (state.initialError) return 'error'
  if (state.stale) return 'stale'
  if (state.refreshing) return 'refreshing'
  return 'ready'
})
const cur = computed(() => auth.user?.base_currency || 'CNY')

const insights = ref({ breakdown: [] })
const paymentHistory = ref([])
const activeSubs = ref([])
const trendMonthOptions = TREND_MONTH_OPTIONS
const trendMonths = ref(6)
const trendError = ref('')
let paymentHistoryRequestId = 0
const currentMonth = (() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}` })()
// 未来支出继续复用前端周期引擎，并补齐窗口内的空月份；隐藏日历的订阅仍属于财务统计。
const futureTrend = computed(() => buildFutureTrend(activeSubs.value, trendMonths.value))
const detail = ref({ recurring: [], one_time: [] })
const ranking = ref([])
const oneTime = ref([])
const upcoming = ref([])
const expired = ref([])
const payments = ref([])
const paymentsCompleteness = ref(null)
const cats = ref([])

function catName(id) {
  if (id == null) return t('sub.uncategorized')
  const c = cats.value.find((x) => x.id === id)
  return c ? c.name : t('sub.uncategorized')
}

function money(value, currency = cur.value, options = {}) { return formatMoney(value, currency, options) }
function cleanText(value) {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}
function joinMeta(...parts) { return parts.map(cleanText).filter(Boolean).join(' · ') }
function ledgerMeta(s) { return joinMeta(s?.plan, catName(s?.category_id)) }
function statusOf(s) { return renewalStatus(s, { emptyStatus: 'ok' }) }

const segments = computed(() => (insights.value.breakdown || []).filter((b) => b.percent > 0))
const donutStyle = computed(() => {
  const bd = insights.value.breakdown || []
  if (!bd.length) return { background: 'var(--border)' }
  let acc = 0
  const stops = []
  bd.forEach((b) => {
    const start = acc
    acc += b.percent
    stops.push(`${categoryColor(b)} ${start}% ${acc}%`)
  })
  if (acc < 100) stops.push(`var(--border) ${acc}% 100%`)
  return { background: `conic-gradient(${stops.join(',')})` }
})
const maxMonthly = computed(() => Math.max(1, ...(insights.value.breakdown || []).map((b) => b.monthly)))
function barW(b) { return Math.round((b.monthly / maxMonthly.value) * 100) }
const recurringCount = computed(() => (detail.value.recurring || []).reduce((a, r) => a + r.count, 0))
const financeCompleteness = computed(() => {
  if (active.value === 'overview') {
    return detail.value.financial_completeness || insights.value.financial_completeness || null
  }
  if (active.value === 'categoryDetail') return detail.value.financial_completeness || null
  if (active.value === 'recentPayments') return paymentsCompleteness.value
  return null
})
// 月度预算：基于月化 run-rate（insights.monthly_total）对比用户预算
const budget = computed(() => auth.user?.monthly_budget ?? null)
const monthlyTotal = computed(() => insights.value.monthly_total || 0)
const budgetOver = computed(() => budget.value !== null && monthlyTotal.value > budget.value)
const budgetPct = computed(() => {
  if (budget.value === null) return 0
  if (budget.value === 0) return monthlyTotal.value > 0 ? 100 : 0
  return Math.min(100, Math.round((monthlyTotal.value / budget.value) * 100))
})
const reportStatus = computed(() => {
  if (expired.value.length) return 'overdue'
  if (upcoming.value.some((s) => {
    const d = daysLeft(s)
    return d !== null && d <= 7
  })) return 'soon'
  return 'ok'
})
const riskRadarRaw = computed(() => {
  const base = {
    overdue: { key: 'overdue', label: t('reports.expired'), count: expired.value.length, amount: 0, missingCurrencies: new Set() },
    soon: { key: 'soon', label: t('sub.statusSoon'), count: 0, amount: 0, missingCurrencies: new Set() },
    ok: { key: 'ok', label: t('sub.statusSafe'), count: 0, amount: 0, missingCurrencies: new Set() },
    oneTime: { key: 'oneTime', label: t('reports.oneTime'), count: oneTime.value.length, amount: 0, missingCurrencies: new Set() }
  }
  function addAmount(bucket, item) {
    const amount = baseAmountOf(item)
    if (amount === null) {
      if (item.currency) bucket.missingCurrencies.add(item.currency)
    } else {
      bucket.amount += amount
    }
  }
  for (const s of expired.value) addAmount(base.overdue, s)
  for (const s of oneTime.value) addAmount(base.oneTime, s)
  for (const s of upcoming.value) {
    const d = daysLeft(s)
    const key = d !== null && d <= 7 ? 'soon' : 'ok'
    base[key].count += 1
    addAmount(base[key], s)
  }
  return Object.values(base).map((bucket) => ({
    ...bucket,
    amountLabel: bucket.missingCurrencies.size
      ? t('reports.radarAmountIncomplete', { currencies: [...bucket.missingCurrencies].join('、') })
      : ''
  }))
})
const riskRadarBars = computed(() => {
  const max = Math.max(1, ...riskRadarRaw.value.map((b) => b.count))
  return riskRadarRaw.value.map((b) => ({ ...b, fill: Math.round((b.count / max) * 100) }))
})
const riskTotal = computed(() => expired.value.length + upcoming.value.length)

async function loadPaymentHistory() {
  const requestedMonths = trendMonths.value
  const requestId = ++paymentHistoryRequestId
  try {
    const response = await api.get('/api/reports/payment-history', { params: { months: requestedMonths } })
    if (requestId === paymentHistoryRequestId && requestedMonths === trendMonths.value) {
      paymentHistory.value = response.data.history || []
      if (response.data.financial_completeness?.is_complete === false) {
        trendError.value = t('reports.incompleteFx', {
          currencies: (response.data.financial_completeness.missing_currencies || []).join('、')
        })
      } else {
        trendError.value = ''
      }
    }
  } catch (error) {
    if (requestId === paymentHistoryRequestId && requestedMonths === trendMonths.value) {
      paymentHistory.value = []
      trendError.value = t('reports.trendLoadFailed')
    }
    throw error
  }
}

async function setTrendMonths(months) {
  if (trendMonths.value === months) return
  trendMonths.value = months
  trendError.value = ''
  try { await loadPaymentHistory() }
  catch { /* 当前请求失败态由 loadPaymentHistory 负责；旧请求不会覆盖新范围。 */ }
}

async function loadOverview() {
  const requestedMonths = trendMonths.value
  const historyRequestId = ++paymentHistoryRequestId
  const results = await Promise.allSettled([
    api.get('/api/reports/insights'),
    api.get('/api/reports/category-detail'),
    api.get('/api/reports/upcoming'),
    api.get('/api/reports/expired'),
    api.get('/api/reports/payment-history', { params: { months: requestedMonths } }),
    api.get('/api/subscriptions', { params: { active: true } })
  ])
  const [ins, det, u, e, hist, subs] = results.map((r) => (r.status === 'fulfilled' ? r.value : null))
  if (!ins || !det || !u || !e || !subs) throw new Error('reports overview unavailable')
  return { requestedMonths, historyRequestId, ins, det, u, e, hist, subs }
}
async function loadInsights() {
  const [r, o, u, e] = await Promise.all([
    api.get('/api/reports/ranking'),
    api.get('/api/reports/one-time'),
    api.get('/api/reports/upcoming'),
    api.get('/api/reports/expired')
  ])
  return { r, o, u, e }
}
async function loadDetail() { return (await api.get('/api/reports/category-detail')).data }
async function loadPayments() { return (await api.get('/api/reports/recent-payments')).data }

function applyOverview(payload) {
  insights.value = payload.ins.data
  if (payload.det) detail.value = payload.det.data
  if (payload.u) upcoming.value = payload.u.data
  if (payload.e) expired.value = payload.e.data
  if (
    payload.historyRequestId === paymentHistoryRequestId
    && payload.requestedMonths === trendMonths.value
  ) {
    paymentHistory.value = payload.hist?.data.history || []
    if (!payload.hist) {
      trendError.value = t('reports.trendLoadFailed')
    } else if (payload.hist.data.financial_completeness?.is_complete === false) {
      trendError.value = t('reports.incompleteFx', {
        currencies: (payload.hist.data.financial_completeness.missing_currencies || []).join('、')
      })
    } else {
      trendError.value = ''
    }
  }
  if (payload.subs) activeSubs.value = payload.subs.data || []
}

const activeRequestGuard = createRequestGuard()
async function loadActive() {
  const tab = active.value
  const state = tabStates[tab]
  const requestId = activeRequestGuard.begin()
  if (state.hasLoaded) state.refreshing = true
  else state.initialLoading = true
  state.initialError = false
  try {
    let payload
    if (tab === 'overview') payload = await loadOverview()
    else if (tab === 'insights') payload = await loadInsights()
    else if (tab === 'categoryDetail') payload = await loadDetail()
    else payload = await loadPayments()
    if (!activeRequestGuard.isCurrent(requestId) || active.value !== tab) return
    if (tab === 'overview') applyOverview(payload)
    else if (tab === 'insights') {
      ranking.value = payload.r.data
      oneTime.value = payload.o.data
      upcoming.value = payload.u.data
      expired.value = payload.e.data
    } else if (tab === 'categoryDetail') {
      detail.value = payload
    } else {
      payments.value = payload.items || []
      paymentsCompleteness.value = payload.financial_completeness || null
    }
    state.hasLoaded = true
    state.stale = false
  } catch {
    if (!activeRequestGuard.isCurrent(requestId) || active.value !== tab) return
    if (state.hasLoaded) state.stale = true
    else state.initialError = true
  } finally {
    if (activeRequestGuard.isCurrent(requestId) && active.value === tab) {
      state.initialLoading = false
      state.refreshing = false
    }
  }
}

watch(active, loadActive)
onMounted(() => {
  loadActive()
  api.get('/api/categories')
    .then((response) => { cats.value = response.data || [] })
    .catch(() => { /* 分类名称是辅助元数据，失败不阻断报表主数据。 */ })
})
</script>

<style scoped>
h1 { margin: 0; }
.finance-warning { margin: 0 0 14px; padding: 10px 12px; border: 1px solid color-mix(in srgb, var(--warning) 45%, var(--border)); border-radius: 10px; background: color-mix(in srgb, var(--warning) 8%, var(--surface)); color: var(--text-soft); font-size: 13px; }
.report-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; margin-bottom: 14px;
  position: relative; overflow: hidden; background: linear-gradient(135deg, color-mix(in srgb, var(--signal-cyan) 10%, var(--surface)), var(--surface)); }
.report-head.overdue { background: linear-gradient(135deg, color-mix(in srgb, var(--danger) 12%, var(--surface)), var(--surface)); }
.report-head.soon { background: linear-gradient(135deg, color-mix(in srgb, var(--warning) 12%, var(--surface)), var(--surface)); }
.report-heading { margin-top: 4px; font-size: 24px; font-weight: 800; letter-spacing: -.02em; }
.report-title p { margin: 6px 0 0; font-size: 14px; }
.hero-kicker { display: flex; align-items: center; gap: 8px; font-size: 11px; text-transform: uppercase; letter-spacing: .18em; color: var(--text-soft); margin-bottom: 6px; }
.hero-kicker .signal-dot { width: 8px; height: 8px; }
.hero-kicker .signal-dot.overdue { background: var(--danger); box-shadow: 0 0 0 3px color-mix(in srgb, var(--danger) 18%, transparent), 0 0 14px color-mix(in srgb, var(--danger) 55%, transparent); }
.hero-kicker .signal-dot.soon { background: var(--warning); box-shadow: 0 0 0 3px color-mix(in srgb, var(--warning) 18%, transparent), 0 0 14px color-mix(in srgb, var(--warning) 55%, transparent); }
.report-head-metrics { display: grid; grid-template-columns: repeat(2, minmax(120px, 1fr)); gap: 8px; min-width: min(360px, 46%); }
.head-metric { border: 1px solid var(--border); border-radius: 14px; background: color-mix(in srgb, var(--surface-2) 78%, transparent); padding: 10px; }
.head-metric span { display: block; font-size: 12px; color: var(--text-soft); margin-bottom: 4px; }
.head-metric strong { font-size: 16px; letter-spacing: -.02em; }
.report-tabs { margin-bottom: 14px; }
.report-tabs button { white-space: nowrap; }
.two { grid-template-columns: 1fr 1fr; }
.sect { margin-bottom: 16px; }
.panel-title { margin-top: 0; display: flex; align-items: center; gap: 8px; justify-content: space-between; flex-wrap: wrap; }
.panel-signal { width: 8px; height: 8px; border-radius: 999px; background: var(--signal-cyan); box-shadow: 0 0 0 3px color-mix(in srgb, var(--signal-cyan) 14%, transparent); flex-shrink: 0; }
.panel-title .panel-signal { margin-right: 2px; }
.panel-title > .panel-signal + * { margin-left: 0; }
.total { font-size: 13px; font-weight: 500; margin-left: auto; }
.danger { color: var(--danger-text); }
.money-cell, .date-cell { white-space: nowrap; }
.status-row { position: relative; }
.status-row td:first-child { border-left: 3px solid transparent; }
.status-row.soon { background: color-mix(in srgb, var(--warning) 6%, transparent); }
.status-row.overdue { background: color-mix(in srgb, var(--danger) 6%, transparent); }
.status-row.oneTime { background: color-mix(in srgb, var(--text-soft) 5%, transparent); }
.status-row.soon td:first-child { border-left-color: var(--warning-text); }
.status-row.overdue td:first-child { border-left-color: var(--danger-text); }
.status-row.ok td:first-child { border-left-color: color-mix(in srgb, var(--success) 55%, transparent); }
.status-row.oneTime td:first-child { border-left-color: color-mix(in srgb, var(--text-soft) 42%, transparent); }
.signal-cell { display: flex; align-items: center; gap: 8px; min-width: 0; }
.event-signal { width: 8px; height: 8px; border-radius: 999px; background: var(--success); flex-shrink: 0; box-shadow: 0 0 0 3px color-mix(in srgb, var(--success) 12%, transparent); }
.soon .event-signal { background: var(--warning); box-shadow: 0 0 0 3px color-mix(in srgb, var(--warning) 14%, transparent); }
.overdue .event-signal { background: var(--danger); box-shadow: 0 0 0 3px color-mix(in srgb, var(--danger) 14%, transparent); }
.oneTime .event-signal { background: var(--text-soft); box-shadow: 0 0 0 3px color-mix(in srgb, var(--text-soft) 12%, transparent); }

.rk { width: 28px; color: var(--text-soft); font-weight: 700; }
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
.budget-card { margin-bottom: 16px; }
.budget-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.budget-track { height: 12px; border-radius: 20px; overflow: hidden; background: color-mix(in srgb, var(--border) 52%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--border) 55%, transparent); }
.budget-fill { height: 100%; border-radius: 20px; background: var(--primary); transition: width .4s ease; }
.budget-fill.over { background: var(--danger); }
.budget-head .over { color: var(--danger-text); font-weight: 700; }
.budget-status { font-size: 12px; margin: 6px 0 0; }
.trend-card { margin-bottom: 16px; overflow: hidden; }
.trend-card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.trend-card-head .panel-title { margin-bottom: 0; }
.trend-range { flex: 0 0 auto; margin: 0; }
.trend-range button { min-height: var(--tap-size); padding: 6px 10px; white-space: nowrap; }
.trend-error { margin: 10px 0 0; color: var(--danger-text); font-size: 13px; }
.kpi { position: relative; overflow: hidden; border-color: color-mix(in srgb, var(--signal-cyan) 18%, var(--border)); }
.kpi-l { font-size: 13px; color: var(--text-soft); }
.kpi-v { font-size: 23px; font-weight: 800; margin-top: 6px; letter-spacing: -.03em; }
.kpi-signal { position: absolute; right: 14px; top: 14px; width: 8px; height: 8px; border-radius: 999px; background: var(--primary); box-shadow: 0 0 0 4px color-mix(in srgb, var(--primary) 12%, transparent); }
.kpi::after { content: ''; position: absolute; right: -20px; top: -20px; width: 70px; height: 70px;
  border-radius: 50%; opacity: .14; pointer-events: none; }
.k1::after, .k1 .kpi-signal { background: var(--primary); }
.k2::after, .k2 .kpi-signal { background: var(--signal-cyan); }
.k3::after, .k3 .kpi-signal { background: var(--success); }
.k4::after, .k4 .kpi-signal { background: var(--warning); }

/* 环形图 */
.chart-card { overflow: hidden; }
.donut-wrap { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
.donut { width: 150px; height: 150px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; box-shadow: 0 0 0 1px var(--border), 0 0 28px color-mix(in srgb, var(--signal-cyan) 10%, transparent); }
.donut-hole { width: 96px; height: 96px; border-radius: 50%; background: var(--surface);
  display: flex; flex-direction: column; align-items: center; justify-content: center; border: 1px solid var(--border); }
.dh-v { font-size: 17px; font-weight: 800; }
.dh-l { font-size: 11px; }
.legend { flex: 1; min-width: 140px; display: flex; flex-direction: column; gap: 6px; }
.lg { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
.lg-n { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* 柱状 */
.bar-row { display: grid; grid-template-columns: 130px 1fr 110px; align-items: center; gap: 10px; margin: 9px 0; }
.bar-label { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-track { background: color-mix(in srgb, var(--border) 52%, transparent); border-radius: 20px; height: 12px; overflow: hidden; box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--border) 55%, transparent); }
.bar-fill { height: 100%; border-radius: 20px; transition: width .4s ease; }
.bar-val { font-size: 13px; color: var(--text-soft); text-align: right; }

/* 续费压力雷达 */
.report-radar { margin-bottom: 16px; overflow: hidden; }
.radar-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 12px; }
.radar-head h3 { margin: 0; }
.risk-total { font-size: 12px; white-space: nowrap; }
.radar-bars { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.radar-bar { display: flex; flex-direction: column; gap: 3px; min-width: 0; border: 1px solid var(--border); border-radius: 12px;
  padding: 9px; background: color-mix(in srgb, var(--surface-2) 78%, transparent); }
.rb-count { font-size: 22px; font-weight: 800; letter-spacing: -.03em; }
.rb-label, .rb-amt { font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rb-track { height: 5px; border-radius: 999px; overflow: hidden; background: color-mix(in srgb, var(--border) 62%, transparent); }
.rb-fill { display: block; height: 100%; border-radius: 999px; }
.radar-bar.overdue { border-color: color-mix(in srgb, var(--danger) 48%, var(--border)); }
.radar-bar.overdue.active { animation: pulse-danger 2s ease-in-out infinite; }
.radar-bar.overdue .rb-count { color: var(--danger-text); }
.radar-bar.overdue .rb-fill { background: var(--danger); }
.radar-bar.soon { border-color: color-mix(in srgb, var(--warning) 48%, var(--border)); }
.radar-bar.soon .rb-count { color: var(--warning-text); }
.radar-bar.soon .rb-fill { background: var(--warning); }
.radar-bar.ok .rb-count { color: var(--success-text); }
.radar-bar.ok .rb-fill { background: var(--success); }
.radar-bar.oneTime .rb-count { color: var(--text-soft); }
.radar-bar.oneTime .rb-fill { background: color-mix(in srgb, var(--text-soft) 44%, var(--border)); }
.signal-panel { position: relative; overflow: hidden; }
.overdue-panel { border-color: color-mix(in srgb, var(--danger) 32%, var(--border)); }
.soon-panel { border-color: color-mix(in srgb, var(--warning) 28%, var(--border)); }
.lifetime-panel, .detail-lifetime { border-color: color-mix(in srgb, var(--text-soft) 20%, var(--border)); }
.detail-recurring { border-color: color-mix(in srgb, var(--signal-cyan) 24%, var(--border)); }

/* 近期付款 */
.payments-card { overflow: hidden; }
.pay-row { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.pay-row:last-child { border-bottom: none; }
.pay-signal { width: 8px; height: 8px; border-radius: 999px; background: var(--success); box-shadow: 0 0 0 3px color-mix(in srgb, var(--success) 12%, transparent); flex-shrink: 0; }
.pay-row.oneTime .pay-signal { background: var(--text-soft); box-shadow: 0 0 0 3px color-mix(in srgb, var(--text-soft) 12%, transparent); }
.pay-ico { width: 34px; height: 34px; border-radius: 9px; background: var(--surface-2); border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
.pay-ico-img { width: 22px; height: 22px; border-radius: 6px; object-fit: contain; }
.pay-main { flex: 1; min-width: 0; }
.pay-n { font-weight: 600; font-size: 14px; }
.pay-d { font-size: 12px; }
.pay-amt { font-weight: 700; font-size: 14px; white-space: nowrap; }

/* 移动端账本列表：由 v-if=isDesktop 控制渲染，此处只管布局 */
.ledger { display: flex; flex-direction: column; }
.ld-row { display: flex; align-items: center; gap: 10px; padding: 11px 4px; border-bottom: 1px solid var(--border);
  min-height: 44px; border-left: 3px solid transparent; padding-left: 8px; }
.ld-row:last-child { border-bottom: none; }
.ld-row.soon { border-left-color: var(--warning-text); background: color-mix(in srgb, var(--warning) 6%, transparent); }
.ld-row.overdue { border-left-color: var(--danger-text); background: color-mix(in srgb, var(--danger) 6%, transparent); }
.ld-row.ok { border-left-color: color-mix(in srgb, var(--success) 55%, transparent); }
.ld-row.oneTime { border-left-color: color-mix(in srgb, var(--text-soft) 40%, transparent); }
.rank-row { border-left-color: color-mix(in srgb, var(--primary) 45%, transparent); }
.ld-rk { width: 22px; height: 22px; flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center;
  border-radius: 999px; background: var(--surface-2); color: var(--text-soft); font-size: 12px; font-weight: 700; }
.ld-ico { width: 26px; height: 26px; border-radius: 7px; object-fit: contain; flex-shrink: 0;
  border: 1px solid var(--border); background: var(--surface-2); }
.ld-main { flex: 1; min-width: 0; }
.ld-n { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ld-s, .ld-meta, .ld-date, .ld-remark { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ld-meta, .ld-date { color: var(--text-soft); }
.ld-remark { color: var(--primary); }
.ld-amt { font-weight: 700; font-size: 14px; text-align: right; white-space: nowrap; }
.ld-amt .muted { font-size: 11px; font-weight: 500; }

@keyframes pulse-danger { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--danger) 40%, transparent); } 50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--danger) 12%, transparent); } }
@media (prefers-reduced-motion: reduce) { .radar-bar.overdue { animation: none; } .bar-fill { transition: none; } }

@media (max-width: 980px) {
  .report-head { flex-direction: column; }
  .report-head-metrics { min-width: 0; width: 100%; }
  .radar-bars { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 720px) {
  .kpis { grid-template-columns: 1fr 1fr; }
  .kpi-v { font-size: 20px; overflow-wrap: anywhere; }
  .two { grid-template-columns: 1fr; }
  .report-head-metrics { grid-template-columns: 1fr; }
  .trend-card-head { align-items: stretch; flex-direction: column; }
  .trend-range { width: 100%; }
  .trend-range button { flex: 1; min-height: 44px; }
  .rb-label, .rb-amt, .ld-s, .ld-meta, .ld-date, .ld-remark { white-space: normal; line-height: 1.3; }
  .ld-remark { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
  .ld-row { align-items: flex-start; }
  .ld-n { white-space: normal; line-height: 1.35; overflow-wrap: anywhere; }
  .ld-amt { white-space: normal; overflow-wrap: anywhere; }
}
@media (max-width: 480px) {
  .bar-row { grid-template-columns: 1fr auto; gap: 6px; }
  .bar-track { grid-column: 1 / -1; }
  .bar-val { text-align: right; }
  .radar-bars { grid-template-columns: 1fr; }
  .pay-row { align-items: flex-start; }
  .pay-amt { font-size: 13px; }
}
</style>
