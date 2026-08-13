<template>
  <div>
    <h1 class="sr-only" tabindex="-1">{{ t('nav.dashboard') }}</h1>
    <DataState
      v-if="dataState !== 'ready'"
      :state="dataState"
      :trust="dataState === 'stale' ? 'stale' : 'unknown'"
      :compact="dataState === 'refreshing' || dataState === 'stale'"
      error-title="雷达总览加载失败"
      stale-title="刷新失败，当前显示上次加载的总览"
      @retry="reload"
    />
    <template v-if="hasMainData">
      <!-- Command Center hero -->
      <div class="hero card" :class="heroStatus">
        <div>
          <div class="hero-kicker"><SignalDot :status="heroStatus" />{{ t('dashboard.commandCenter') }}</div>
          <div class="hi">{{ t('dashboard.greeting', { name: auth.user?.username || '' }) }}</div>
          <div class="sub muted">{{ radarHero }}</div>
        </div>
        <button class="btn" type="button" @click="openEdit(null)">+ {{ t('sub.add') }}</button>
      </div>

      <!-- 续费雷达 -->
      <div class="card radar" v-if="radarTotal">
        <div class="radar-head">
          <h3>{{ t('dashboard.radarTitle') }}</h3>
          <router-link to="/calendar" class="more">{{ t('dashboard.viewAll') }} →</router-link>
        </div>
        <RadarBars :bars="radarBars" :currency="cur" />
      </div>

      <p v-if="financeIncomplete" class="finance-warning" role="status">
        {{ t('reports.incompleteFx', { currencies: missingCurrencies }) }}
      </p>

      <!-- KPI -->
      <div class="grid stats">
        <div class="card stat s1" :class="{ 'budget-over': budgetOver }">
          <div class="badge" v-html="icon('wallet')"></div>
          <div>
            <div class="muted">{{ t('dashboard.monthSpend') }}</div>
            <div class="big mono-data">{{ fmt(data.month_spend) }}</div>
            <div v-if="budgetOver" class="budget-warn">{{ t('reports.budgetOver', { n: fmt(data.month_spend - budget) }) }}</div>
          </div>
        </div>
        <div class="card stat s2">
          <div class="badge" v-html="icon('trending')"></div>
          <div><div class="muted">{{ t('dashboard.yearSpend') }}</div><div class="big mono-data">{{ fmt(data.year_spend) }}</div></div>
        </div>
        <div class="card stat s3">
          <div class="badge" v-html="icon('package')"></div>
          <div><div class="muted">{{ t('dashboard.active') }}</div><div class="big mono-data">{{ data.active_count }}</div></div>
        </div>
        <div class="card stat s4" :class="{ alert: expiredCount > 0 }">
          <div class="badge" v-html="icon('alert')"></div>
          <div><div class="muted">{{ t('dashboard.overdue') }}</div><div class="big mono-data">{{ expiredCount }}</div></div>
        </div>
      </div>

      <div class="grid main">
        <!-- 即将到期 -->
        <div class="card">
          <div class="card-h">
            <h3>{{ t('dashboard.upcoming') }}</h3>
            <router-link to="/calendar" class="more">{{ t('dashboard.viewAll') }} →</router-link>
          </div>
          <p v-if="!data.upcoming.length" class="muted">{{ t('dashboard.none') }}</p>
          <div v-for="s in data.upcoming" :key="s.id" class="line event-line clickable"
               :class="statusOf(s)" role="button" tabindex="0"
               :aria-label="s.name"
               @click="openDetail(s)" @keydown="onItemKeydown($event, s)">
            <span class="event-signal"></span>
            <span class="l-name">
              <ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="mini-ico" />
              <span class="l-txt">{{ s.name }}</span>
            </span>
            <span class="l-right">
              <span class="tag" :class="dueClass(s)">{{ dueText(s, t) }}</span>
              <b class="mono-data">{{ s.amount_in_base == null ? t('reports.rateUnavailable') : fmt(s.amount_in_base) }}</b>
            </span>
          </div>
        </div>

        <!-- 分类占比 -->
        <div class="card">
          <div class="card-h"><h3>{{ t('dashboard.byCategory') }}</h3>
            <router-link to="/reports" class="more">{{ t('dashboard.viewAll') }} →</router-link></div>
          <div v-if="breakdown.length" class="donut-wrap">
            <div class="donut" :style="donutStyle"><div class="donut-hole"></div></div>
            <div class="legend">
              <div v-for="b in breakdown.slice(0, 6)" :key="categoryVisualKey(b)" class="lg">
                <span class="dot" :style="{ background: categoryColor(b) }"></span>
                <span class="lg-n">{{ b.category }}</span>
                <span class="muted">{{ b.percent }}%</span>
              </div>
            </div>
          </div>
          <p v-else class="muted">{{ t('dashboard.none') }}</p>
        </div>
      </div>

      <!-- 分类总览：按分类展示全部订阅 + 颜色警示 -->
      <div class="card" v-if="catGroups.length">
        <h3>{{ t('dashboard.catOverview') }}</h3>
        <div class="cat-cols">
          <div v-for="g in catGroups" :key="g.key" class="cat-col">
            <div class="cc-head">
              <span>{{ g.icon }} {{ g.name }}</span>
              <span class="cc-count">{{ g.items.length }}</span>
            </div>
            <div v-for="s in g.items" :key="s.id" class="cc-item clickable" :class="statusOf(s)"
                 role="button" tabindex="0" :aria-label="s.name"
                 @click="openDetail(s)" @keydown="onItemKeydown($event, s)">
              <span class="cc-dot"></span>
              <ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="mini-ico" />
              <span class="cc-n">{{ s.name }}</span>
              <span class="cc-d">{{ s.next_renewal_date ? dueText(s, t) : t('sub.oneTime') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 最近订阅 -->
      <div class="card">
        <h3>{{ t('dashboard.recent') }}</h3>
        <p v-if="!data.recent.length" class="muted">{{ t('dashboard.none') }}</p>
        <div class="recent-grid">
          <div v-for="s in data.recent" :key="s.id" class="rc clickable"
               role="button" tabindex="0" :aria-label="s.name"
               @click="openDetail(s)" @keydown="onItemKeydown($event, s)">
            <ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="rc-ico-img" />
            <div class="rc-main"><div class="rc-n">{{ s.name }}</div>
              <div class="muted rc-a">{{ s.amount_in_base == null ? t('reports.rateUnavailable') : fmt(s.amount_in_base) }}</div></div>
          </div>
        </div>
      </div>
    </template>

    <!-- 订阅详情弹窗：复用只读详情组件，底部直接操作 -->
    <AppModal v-model="showDetail" :title="detailTarget?.name" width="640px" :close-label="t('common.close')" @close="closeDetail">
      <SubscriptionCardDetails
        v-if="detailTarget"
        :subscription="detailTarget"
        expanded
        detail-id="dash-detail"
        :category-name="detailCategoryName"
        :base-currency="cur"
        :base-amount="detailBaseAmount"
        :show-base-amount="detailShowBase"
        :cycle-text="detailCycleText"
        :payment-name="detailPaymentName"
        :bundle-name="detailBundleName"
        :family-text="detailFamilyText"
      />
      <template #footer>
        <button v-if="detailTarget?.billing_type === 'recurring'"
                class="btn detail-action detail-action-primary" :disabled="busy"
                @click="askRenew(detailTarget)">
          {{ detailTarget?.is_keepalive ? t('sub.keepalive.renewMark') : t('sub.renewMark') }}
        </button>
        <button class="btn ghost detail-action" :disabled="busy" @click="openEdit(detailTarget)">{{ t('sub.edit') }}</button>
        <button class="btn ghost detail-action detail-action-danger" :disabled="busy" @click="askDelete(detailTarget)">{{ t('sub.delete') }}</button>
      </template>
    </AppModal>

    <RenewSubscriptionModal
      v-if="renewTarget"
      :target="renewTarget"
      v-model:mode="renewMode"
      :renewing="renewing"
      :preview-today="previewToday"
      :preview-due="previewDue"
      @close="closeRenew"
      @confirm="confirmRenew"
    />

    <DeleteSubscriptionModal
      v-if="delTarget"
      :target="delTarget"
      v-model:password="delPwd"
      :error="delErr"
      :deleting="deleting"
      @close="closeDelete"
      @confirm="confirmDelete"
    />

    <SubscriptionFormModal
      v-if="showForm"
      :subscription="formTarget"
      :currencies="currencies"
      :categories="cats"
      :methods="methods"
      :bundles="bundles"
      :icon-library="iconLib"
      @close="closeForm"
      @saved="onFormSaved"
      @bundle-created="onBundleCreated"
    />

    <AppToastRegion :toasts="toasts" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import AppModal from '../components/AppModal.vue'
import AppToastRegion from '../components/AppToastRegion.vue'
import DataState from '../components/DataState.vue'
import RadarBars from '../components/RadarBars.vue'
import ServiceIcon from '../components/ServiceIcon.vue'
import SignalDot from '../components/SignalDot.vue'
import DeleteSubscriptionModal from '../components/subscriptions/DeleteSubscriptionModal.vue'
import RenewSubscriptionModal from '../components/subscriptions/RenewSubscriptionModal.vue'
import SubscriptionCardDetails from '../components/subscriptions/SubscriptionCardDetails.vue'
import SubscriptionFormModal from '../components/subscriptions/SubscriptionFormModal.vue'
import { useAuth } from '../stores/auth'
import { useBodyLock } from '../composables/useBodyLock'
import { useSubscriptionActions } from '../composables/useSubscriptionActions'
import { useToasts } from '../composables/useToasts'
import { icon } from '../icons'
import { categoryColor, categoryVisualKey } from '../utils/categoryVisual'
import { daysLeft } from '../utils/date'
import { createRequestGuard } from '../utils/dataRequest'
import { emojiOf } from '../utils/icon'
import { amountOf, formatMoney, hasBaseEquivalent } from '../utils/money'
import { buildRenewalRadarEvents } from '../utils/recurrence'
import { radarBucket as renewalRadarBucket, dueText, renewalStatus } from '../utils/renewal'

const { t } = useI18n()
const auth = useAuth()
const initialLoading = ref(true)
const refreshing = ref(false)
const initialError = ref(false)
const stale = ref(false)
const hasMainData = ref(false)
const dataState = computed(() => {
  if (initialLoading.value) return 'loading'
  if (initialError.value) return 'error'
  if (stale.value) return 'stale'
  if (refreshing.value) return 'refreshing'
  return 'ready'
})
const data = ref({ upcoming: [], recent: [] })
const breakdown = ref([])
const expiredCount = ref(0)
const allSubs = ref([])
const cats = ref([])
const currencies = ref([])
const methods = ref([])
const bundles = ref([])
const iconLib = ref([])

const { toasts, add: toast } = useToasts()

// 订阅详情弹窗：detailId 指向当前打开的订阅，detailTarget 从刷新后的数据实时取，
// 避免续费/编辑/删除后详情仍显示旧快照；订阅被删则 detailTarget 变 null 自动收起。
const detailId = ref(null)
const showDetail = computed({
  get: () => detailId.value !== null,
  set: (v) => { if (!v) detailId.value = null }
})
function openDetail(s) {
  detailId.value = s.id
}
function closeDetail() {
  detailId.value = null
}
function onItemKeydown(e, s) {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    openDetail(s)
  }
}
const detailTarget = computed(() => {
  if (detailId.value === null) return null
  const pool = [
    ...allSubs.value,
    ...(data.value.upcoming || []),
    ...(data.value.recent || [])
  ]
  return pool.find((s) => s.id === detailId.value) || null
})
// 订阅在操作后被删除/停用导致 detailTarget 失联时，自动关闭弹窗。
watch(detailTarget, (s) => { if (!s) detailId.value = null })

// 仅最新一批 reload 的结果才写入状态，避免慢请求的旧快照覆盖较新操作结果。
const reloadGuard = createRequestGuard()
async function reload() {
  const requestId = reloadGuard.begin()
  if (hasMainData.value) refreshing.value = true
  else initialLoading.value = true
  initialError.value = false
  const results = await Promise.allSettled([
    api.get('/api/dashboard'),
    api.get('/api/reports/insights'),
    api.get('/api/reports/expired'),
    api.get('/api/subscriptions', { params: { active: true } }),
    api.get('/api/categories'),
    api.get('/api/payment-methods'),
    api.get('/api/bundles'),
    api.get('/api/currencies'),
    api.get('/api/icons/library')
  ])
  if (!reloadGuard.isCurrent(requestId)) return
  const [d, ins, exp, subs, c, m, b, cur, lib] = results.map((r) => (r.status === 'fulfilled' ? r.value : null))
  // Dashboard、分类洞察、过期数量与 occurrence 雷达共同构成主数据；表单辅助元数据失败只降级对应区域。
  if (d && ins && exp && subs) {
    data.value = d.data
    allSubs.value = subs.data || []
    hasMainData.value = true
    stale.value = false
  } else if (hasMainData.value) {
    stale.value = true
  } else {
    initialError.value = true
  }
  if (ins) breakdown.value = ins.data.breakdown || []
  if (exp) expiredCount.value = (exp.data || []).length
  if (c) cats.value = c.data || []
  if (m) methods.value = m.data || []
  if (b) bundles.value = b.data || []
  if (cur) currencies.value = cur.data || []
  if (lib) iconLib.value = lib.data || []
  initialLoading.value = false
  refreshing.value = false
}

const {
  renewTarget, renewMode, renewing,
  delTarget, delPwd, delErr, deleting,
  showForm, formTarget, busy,
  askRenew, closeRenew, confirmRenew, previewToday, previewDue,
  askDelete, closeDelete, confirmDelete,
  openEdit, closeForm, onFormSaved, onBundleCreated
} = useSubscriptionActions({
  reload,
  toast,
  onBundleCreated: (bundle) => { bundles.value.push(bundle) }
})

// 统一汇总雷达页 overlay 状态，交给引用计数式 body lock 管理。
const dashboardOverlays = computed(() =>
  showDetail.value || showForm.value || !!renewTarget.value || !!delTarget.value
)
useBodyLock(dashboardOverlays, 'dashboard-overlays')

const cur = computed(() => auth.user?.base_currency || 'CNY')
function fmt(v) { return formatMoney(v, cur.value) }
const budget = computed(() => auth.user?.monthly_budget ?? null)
const financeIncomplete = computed(() => data.value.financial_completeness?.is_complete === false)
const missingCurrencies = computed(() => (data.value.financial_completeness?.missing_currencies || []).join('、'))
const budgetOver = computed(() => budget.value !== null && (data.value.month_spend || 0) > budget.value)
function dueClass(s) {
  const d = daysLeft(s)
  if (d === null) return ''
  return d < 0 ? 'danger' : d <= 3 ? 'warn' : ''
}
const radarRaw = computed(() => {
  const base = {
    overdue: { key: 'overdue', label: t('dashboard.radarOverdue'), count: 0, amount: 0, to: '/reports' },
    d3: { key: 'd3', label: t('dashboard.radar3'), count: 0, amount: 0, to: '/calendar' },
    d7: { key: 'd7', label: t('dashboard.radar7'), count: 0, amount: 0, to: '/calendar' },
    d30: { key: 'd30', label: t('dashboard.radar30'), count: 0, amount: 0, to: '/calendar' }
  }
  const events = buildRenewalRadarEvents(allSubs.value, { includeHidden: true })
  for (const s of events) {
    const key = renewalRadarBucket(s, { includeHidden: true })
    if (!key) continue
    base[key].count += 1
    base[key].amount += amountOf(s)
  }
  return Object.values(base)
})
const radarTotal = computed(() => radarRaw.value.reduce((n, b) => n + b.count, 0))
const radarBars = computed(() => {
  const max = Math.max(1, ...radarRaw.value.map((b) => b.count))
  return radarRaw.value.map((b) => ({ ...b, fill: Math.round((b.count / max) * 100) }))
})
const heroStatus = computed(() => {
  if (radarRaw.value.find((b) => b.key === 'overdue')?.count) return 'overdue'
  if (radarRaw.value.find((b) => b.key === 'd3')?.count || radarRaw.value.find((b) => b.key === 'd7')?.count) return 'soon'
  return 'ok'
})
const radarHero = computed(() => {
  if (!radarTotal.value) return t('dashboard.subtitle')
  const amount = radarRaw.value.reduce((n, b) => n + b.amount, 0)
  return t('dashboard.radarHero', { n: radarTotal.value, amount: fmt(amount) })
})
function statusOf(s) { return renewalStatus(s) }

const catGroups = computed(() => {
  const byCat = {}
  for (const s of allSubs.value) {
    const key = s.category_id == null ? 'none' : String(s.category_id)
    ;(byCat[key] ||= []).push(s)
  }
  const order = Object.keys(byCat).sort((a, b) => {
    if (a === 'none') return 1
    if (b === 'none') return -1
    return 0
  })
  return order.map((key) => {
    const c = cats.value.find((x) => String(x.id) === key)
    const items = byCat[key].slice().sort((a, b) => {
      const rank = { overdue: 0, soon: 1, ok: 2, oneTime: 3 }
      return rank[statusOf(a)] - rank[statusOf(b)]
    })
    return {
      key,
      icon: key === 'none' ? '🗂️' : (c?.icon || '📁'),
      name: key === 'none' ? t('sub.uncategorized') : (c?.name || key),
      items
    }
  })
})

const donutStyle = computed(() => {
  if (!breakdown.value.length) return { background: 'var(--border)' }
  let acc = 0
  const stops = []
  breakdown.value.forEach((b) => {
    const start = acc; acc += b.percent
    stops.push(`${categoryColor(b)} ${start}% ${acc}%`)
  })
  if (acc < 100) stops.push(`var(--border) ${acc}% 100%`)
  return { background: `conic-gradient(${stops.join(',')})` }
})

// 详情弹窗派生字段：与订阅账本同款解析逻辑，保证两页展示一致。
const DASH = '-'
const detailCategoryName = computed(() => {
  const s = detailTarget.value
  if (!s) return ''
  if (s.category_id == null) return t('sub.uncategorized')
  const c = cats.value.find((x) => String(x.id) === String(s.category_id))
  return c?.name || ''
})
const detailPaymentName = computed(() => {
  const s = detailTarget.value
  if (!s) return ''
  const p = methods.value.find((x) => x.id === s.payment_method_id)
  return p ? `${p.icon || ''} ${p.name}`.trim() : ''
})
const detailBundleName = computed(() => {
  const s = detailTarget.value
  if (!s) return ''
  const b = bundles.value.find((x) => x.id === s.bundle_id)
  return b ? b.name : ''
})
const detailFamilyText = computed(() => {
  const s = detailTarget.value
  if (!s || !s.family_members || !s.family_members.length) return DASH
  return s.family_members.join('、')
})
const detailCycleText = computed(() => {
  const s = detailTarget.value
  if (!s || s.billing_type !== 'recurring') return ''
  const n = s.cycle_count > 1 ? s.cycle_count + ' ' : ''
  return n + t('sub.' + s.cycle)
})
const detailShowBase = computed(() => detailTarget.value ? hasBaseEquivalent(detailTarget.value, cur.value) : false)
const detailBaseAmount = computed(() => detailTarget.value ? amountOf(detailTarget.value) : 0)

onMounted(reload)
</script>

<style scoped>
.hero { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 16px;
  background: linear-gradient(120deg, color-mix(in srgb, var(--signal-cyan) 10%, var(--surface)), var(--surface)); }
.hero.overdue { background: linear-gradient(120deg, color-mix(in srgb, var(--danger) 12%, var(--surface)), var(--surface)); }
.hero.soon { background: linear-gradient(120deg, color-mix(in srgb, var(--warning) 12%, var(--surface)), var(--surface)); }
.hero-kicker { display: flex; align-items: center; gap: 8px; font-size: 11px; text-transform: uppercase; letter-spacing: .18em; color: var(--text-soft); margin-bottom: 6px; }
.hero-kicker .signal-dot { width: 8px; height: 8px; }
.hero-kicker .signal-dot.overdue { background: var(--danger); box-shadow: 0 0 0 3px color-mix(in srgb, var(--danger) 18%, transparent), 0 0 14px color-mix(in srgb, var(--danger) 55%, transparent); }
.hero-kicker .signal-dot.soon { background: var(--warning); box-shadow: 0 0 0 3px color-mix(in srgb, var(--warning) 18%, transparent), 0 0 14px color-mix(in srgb, var(--warning) 55%, transparent); }
.hi { font-size: 20px; font-weight: 800; letter-spacing: -.02em; }
.sub { font-size: 14px; margin-top: 4px; }

/* 续费雷达 */
.radar { margin-bottom: 16px; }
.radar-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.radar-head h3 { margin: 0; }
.radar-bars { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.radar-bar { display: flex; flex-direction: column; gap: 4px; padding: 12px; border: 1px solid var(--border);
  border-radius: 12px; background: var(--surface-2); text-decoration: none; color: var(--text); }
.rb-count { font-size: 26px; font-weight: 800; letter-spacing: -.02em; line-height: 1; }
.rb-label { font-size: 12px; font-weight: 600; color: var(--text-soft); }
.rb-amt { font-size: 12px; }
.rb-track { height: 6px; border-radius: 999px; background: color-mix(in srgb, var(--border) 60%, transparent); overflow: hidden; margin-top: 4px; }
.rb-fill { display: block; height: 100%; border-radius: 999px; }
.radar-bar.overdue { border-color: color-mix(in srgb, var(--danger) 50%, var(--border)); animation: pulse-danger 2s ease-in-out infinite; }
.radar-bar.overdue .rb-count { color: var(--danger-text); }
.radar-bar.overdue .rb-fill { background: var(--danger); }
.radar-bar.d3 { border-color: color-mix(in srgb, var(--warning) 50%, var(--border)); }
.radar-bar.d3 .rb-count { color: var(--warning-text); }
.radar-bar.d3 .rb-fill { background: var(--warning); }
.radar-bar.d7 .rb-count { color: var(--primary); }
.radar-bar.d7 .rb-fill { background: var(--primary); }
.radar-bar.d30 .rb-count { color: var(--text-soft); }
.radar-bar.d30 .rb-fill { background: color-mix(in srgb, var(--primary) 40%, var(--border)); }
@keyframes pulse-danger { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--danger) 40%, transparent); } 50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--danger) 12%, transparent); } }
@media (prefers-reduced-motion: reduce) { .radar-bar.overdue { animation: none; } }

.finance-warning { margin: 0 0 16px; padding: 10px 12px; border: 1px solid color-mix(in srgb, var(--warning) 45%, var(--border)); border-radius: 10px; background: color-mix(in srgb, var(--warning) 8%, var(--surface)); color: var(--text-soft); font-size: 13px; }
.stats { grid-template-columns: repeat(4, 1fr); margin-bottom: 16px; }
.stat { display: flex; align-items: center; gap: 14px; }
.stat .badge { width: 48px; height: 48px; border-radius: 14px; display: flex; align-items: center;
  justify-content: center; flex-shrink: 0; }
.stat .badge :deep(svg) { width: 24px; height: 24px; }
.stat.s1 .badge { background: #eef0ff; color: #5b5bd6; }
.stat.s2 .badge { background: #e0f7f1; color: #0e9f6e; }
.stat.s3 .badge { background: #fff1e6; color: #f59e0b; }
.stat.s4 .badge { background: #fee2e2; color: #ef4444; }
.stat.s4.alert { border-color: var(--danger-text); }
.stat.budget-over { border-color: var(--danger-text); box-shadow: 0 0 0 1px var(--danger); }
.budget-warn { font-size: 12px; color: var(--danger-text); font-weight: 600; margin-top: 2px; }
.stat .big { font-size: 24px; font-weight: 700; margin-top: 2px; letter-spacing: -.02em; }

.main { grid-template-columns: 1.2fr 1fr; margin-bottom: 16px; }
.card-h { display: flex; justify-content: space-between; align-items: center; }
.card-h h3 { margin: 0; }
.more { font-size: 13px; }
h3 { margin-top: 0; }
.line { display: flex; justify-content: space-between; align-items: center; padding: 9px 0;
  border-bottom: 1px solid var(--border); font-size: 14px; }
.line:last-child { border-bottom: none; }
.event-line { gap: 8px; border-radius: 10px; padding: 8px 6px; }
.event-line.soon { background: color-mix(in srgb, var(--warning) 8%, transparent); }
.event-line.overdue { background: color-mix(in srgb, var(--danger) 8%, transparent); }
.event-signal { width: 8px; height: 8px; border-radius: 999px; background: var(--success); flex-shrink: 0; }
.event-line.soon .event-signal { background: var(--warning); box-shadow: 0 0 0 3px color-mix(in srgb, var(--warning) 14%, transparent); }
.event-line.overdue .event-signal { background: var(--danger); box-shadow: 0 0 0 3px color-mix(in srgb, var(--danger) 14%, transparent); }
.l-name { display: flex; align-items: center; gap: 8px; min-width: 0; }
.l-txt { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.l-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; min-width: 0; }
/* 列表/分类项中的小图标：图片或 emoji 统一尺寸 */
.mini-ico { width: 20px; height: 20px; border-radius: 5px; object-fit: contain; flex-shrink: 0;
  border: 1px solid var(--border); background: var(--surface-2); }
.mini-emoji { width: 20px; height: 20px; display: inline-flex; align-items: center; justify-content: center;
  font-size: 15px; flex-shrink: 0; }
.mini-emoji.sm { font-size: 14px; }
.tag.warn { background: #fef3c7; color: #b45309; }
.tag.danger { background: #fee2e2; color: #b91c1c; }

.donut-wrap { display: flex; align-items: center; gap: 18px; margin-top: 8px; }
.donut { width: 120px; height: 120px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; }
.donut-hole { width: 74px; height: 74px; border-radius: 50%; background: var(--surface); }
.legend { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.lg { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
.lg-n { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* 分类总览 */
.cat-cols { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; margin-top: 6px; }
.cat-col { border: 1px solid var(--border); border-radius: 12px; padding: 12px; }
.cc-head { display: flex; justify-content: space-between; align-items: center; font-weight: 600; font-size: 14px; margin-bottom: 8px; }
.cc-count { background: var(--surface-2); color: var(--text-soft); border-radius: 20px; padding: 1px 8px; font-size: 12px; }
.cc-item { display: flex; align-items: center; gap: 8px; font-size: 13px; padding: 5px 0; }
.cc-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--success); flex-shrink: 0; }
.cc-item.soon .cc-dot { background: var(--warning); }
.cc-item.overdue .cc-dot { background: var(--danger); }
.cc-item.oneTime .cc-dot { background: var(--text-soft); opacity: .4; }
.cc-n { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cc-d { font-size: 12px; color: var(--text-soft); white-space: nowrap; }
.cc-item.overdue .cc-d { color: var(--danger-text); font-weight: 600; }
.cc-item.soon .cc-d { color: var(--warning-text); font-weight: 600; }

.recent-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; }
.rc { display: flex; align-items: center; gap: 10px; padding: 10px; border: 1px solid var(--border); border-radius: 10px; }
.rc-ico { font-size: 20px; width: 26px; text-align: center; flex-shrink: 0; }
.rc-ico-img { width: 26px; height: 26px; border-radius: 7px; object-fit: contain; flex-shrink: 0;
  border: 1px solid var(--border); background: var(--surface-2); }
.rc-main { min-width: 0; }
.rc-n { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rc-a { font-size: 12px; }

/* 可点击的订阅条目：键盘可达 + 轻量 hover 反馈，不破坏现有警示底色 */
.clickable { cursor: pointer; transition: background .15s ease, box-shadow .15s ease; }
.clickable:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.event-line.clickable:hover { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--primary) 22%, transparent); }
.cc-item.clickable:hover { background: color-mix(in srgb, var(--primary) 6%, transparent); }
.rc.clickable:hover { border-color: color-mix(in srgb, var(--primary) 40%, var(--border)); box-shadow: var(--shadow); }
/* 详情操作条：主操作柔和强调，编辑保持中性，删除降为红色描边而非大块实心警示。 */
.detail-action { box-shadow: none; }
.detail-action-primary { color: var(--primary); background: var(--primary-soft);
  border: 1px solid color-mix(in srgb, var(--primary) 30%, var(--border)); }
.detail-action-danger { color: var(--danger-text); background: transparent;
  border-color: color-mix(in srgb, var(--danger) 42%, var(--border)); }
.detail-action:hover { transform: none; box-shadow: none; }
.detail-action-primary:hover { color: var(--primary); background: color-mix(in srgb, var(--primary-soft) 72%, var(--primary) 10%); }
.detail-action-danger:hover { color: var(--danger-text); background: color-mix(in srgb, var(--danger) 8%, transparent); border-color: var(--danger-text); }
/* 详情弹窗底部按钮：移动端横向等分紧凑排列。 */
@media (max-width: 980px) { .stats { grid-template-columns: 1fr 1fr; } .main { grid-template-columns: 1fr; } }
@media (max-width: 720px) {
  .stats { grid-template-columns: 1fr 1fr; }
  .radar-bars { grid-template-columns: 1fr 1fr; }
  .hero { flex-direction: column; align-items: stretch; }
  .hero .btn { margin-top: 4px; width: 100%; }
  .sub { line-height: 1.55; }
  .stat { align-items: flex-start; gap: 10px; }
  .stat .badge { width: 40px; height: 40px; }
  .stat .badge :deep(svg) { width: 20px; height: 20px; }
  .stat .big { font-size: 20px; overflow-wrap: anywhere; }
  .event-line { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: start; }
  .l-name { align-items: flex-start; }
  .l-txt { white-space: normal; line-height: 1.35; }
  .l-right { grid-column: 2; flex-wrap: wrap; justify-content: flex-start; }
  .donut-wrap { flex-wrap: wrap; }
  .cat-cols, .recent-grid { grid-template-columns: 1fr; }
  /* 详情弹窗底部三按钮：移动端横向等分紧凑排列，避免三个全宽大按钮纵向堆叠 */
  :deep(.modal-foot) { gap: 6px; }
  :deep(.modal-foot) .btn { flex: 1 1 0; min-height: var(--tap-size); padding: 6px 8px; font-size: 13px; }
}
@media (max-width: 430px) { .stats { grid-template-columns: 1fr; } }
</style>
