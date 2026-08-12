<template>
  <div>
    <DataState
      v-if="dataState !== 'ready'"
      :state="dataState"
      :trust="dataState === 'stale' ? 'stale' : 'unknown'"
      :compact="dataState === 'refreshing' || dataState === 'stale'"
      error-title="续费日历加载失败"
      stale-title="刷新失败，当前显示上次加载的日历"
      @retry="reload"
    />
    <template v-if="hasLoaded">
    <div class="cal-hero card radar-grid-bg" :class="heroStatus">
      <div class="cal-hero-main">
        <div class="hero-kicker">
          <SignalDot :status="heroStatus" />{{ t('calendar.trajectory') }}
        </div>
        <div class="title">
          <span class="month">{{ monthName }}</span>
          <span class="year muted mono-data">{{ year }}</span>
        </div>
        <div class="cal-sub muted">{{ calendarSummary }}</div>
      </div>
      <div class="cal-ops">
        <div class="nav" :aria-label="t('calendar.monthNavigation')">
          <button class="navbtn" :aria-label="t('calendar.prevMonth')" @click="move(-1)">‹</button>
          <button class="today-btn" @click="goToday">{{ t('calendar.today') }}</button>
          <button class="navbtn" :aria-label="t('calendar.nextMonth')" @click="move(1)">›</button>
        </div>
        <div class="today-radar" role="region" :aria-label="t('calendar.todayRadar')">
          <div class="today-radar-label muted">{{ t('calendar.todayRadar') }}</div>
          <RadarBars :bars="radarBars" :currency="cur" wrapper-class="cal-radar-bars" />
        </div>
      </div>
    </div>

    <div class="card cal-card">
      <!-- 桌面：7 列月历 -->
      <div class="cal">
        <div class="dow" v-for="d in dows" :key="d">{{ d }}</div>
        <div v-for="(cell, i) in cells" :key="i" class="cell"
             :class="[{ out: !cell.inMonth, today: cell.isToday, active: cell.events.length }, groupStatus(cell.events)]">
          <div class="dnum"><span class="num mono-data">{{ cell.day }}</span></div>
          <div class="evs">
            <div v-for="ev in cell.events.slice(0, 3)" :key="ev.id" class="ev clickable"
                 :class="statusOf(ev)" :style="{ '--c': evColor(ev) }" :title="ev.name"
                 role="button" tabindex="0" :aria-label="ev.name"
                 @click="openDetail(ev)" @keydown="onItemKeydown($event, ev)">
              <span class="ev-dot"></span>
              <ServiceIcon :src="ev.icon" :name="ev.name" :fallback="emojiOf(ev)" class="ev-ico" />
              <span class="ev-name">{{ ev.name }}</span>
            </div>
            <button v-if="cell.events.length > 3" class="ev more" type="button"
                    :aria-label="t('calendar.openDayEvents', { date: cell.key, n: cell.events.length })"
                    @click="openDayEvents(cell)">
              {{ t('calendar.more', { n: cell.events.length - 3 }) }}
            </button>
          </div>
        </div>
      </div>

      <!-- 移动端：议程列表 -->
      <div class="agenda">
        <div v-for="d in agendaDays" :key="d.key" class="ag-day" :class="[{ today: d.isToday }, groupStatus(d.events)]">
          <div class="ag-head">
            <span class="ag-date">{{ d.label }}</span>
            <span class="ag-count mono-data">{{ d.events.length }}</span>
          </div>
          <div v-for="ev in d.events" :key="ev.id" class="ag-ev clickable" :class="statusOf(ev)"
               :style="{ '--c': evColor(ev) }"
               role="button" tabindex="0" :aria-label="ev.name"
               @click="openDetail(ev)" @keydown="onItemKeydown($event, ev)">
            <span class="ag-signal"></span>
            <ServiceIcon :src="ev.icon" :name="ev.name" :fallback="emojiOf(ev)" class="ag-ico" />
            <span class="ag-name">{{ ev.name }}</span>
            <MoneyText v-if="ev.amount" class="ag-amt" :value="ev.amount" :currency="ev.currency" position="suffix" muted />
          </div>
        </div>
        <div v-if="!agendaDays.length" class="ag-empty muted">{{ t('calendar.noEvents') }}</div>
      </div>
    </div>

    <AppModal v-model="showDayEvents" :title="dayEventsTitle" width="560px" :close-label="t('common.close')" @close="closeDayEvents">
      <div class="day-events-list">
        <button v-for="ev in dayEvents" :key="ev.id" type="button" class="day-event" @click="openDayEventDetail(ev)">
          <ServiceIcon :src="ev.icon" :name="ev.name" :fallback="emojiOf(ev)" class="day-event-ico" />
          <span class="day-event-main">
            <strong>{{ ev.name }}</strong>
            <span class="muted">{{ ev.occurrence_date }}</span>
          </span>
          <MoneyText v-if="ev.amount" :value="ev.amount" :currency="ev.currency" position="suffix" muted />
        </button>
      </div>
    </AppModal>

    <!-- 订阅详情弹窗：详情/续费/编辑/删除一律基于原始订阅（点击的是周期展开后的 occurrence） -->
    <AppModal v-model="showDetail" :title="detailTarget?.name" width="640px" :close-label="t('common.close')" @close="closeDetail">
      <SubscriptionCardDetails
        v-if="detailTarget"
        :subscription="detailTarget"
        expanded
        detail-id="cal-detail"
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

    <div class="toast-wrap">
      <div v-for="tst in toasts" :key="tst.id" class="toast" :class="tst.type">{{ tst.msg }}</div>
    </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import AppModal from '../components/AppModal.vue'
import DataState from '../components/DataState.vue'
import MoneyText from '../components/MoneyText.vue'
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
import { toISODate } from '../utils/date'
import { useDataRequest } from '../utils/dataRequest'
import { emojiOf } from '../utils/icon'
import { amountOf, baseAmountOf, formatMoney, hasBaseEquivalent } from '../utils/money'
import { buildRenewalRadarEvents, expandRenewalsInRange, groupRenewalEventsByDate } from '../utils/recurrence'
import { groupRenewalStatus, radarBucket as renewalRadarBucket, renewalStatus } from '../utils/renewal'

const { t } = useI18n()
const auth = useAuth()
const now = new Date()
const year = ref(now.getFullYear())
const month = ref(now.getMonth())
const dataRequest = useDataRequest({ initialData: [] })
const subs = dataRequest.data
const dataState = computed(() => dataRequest.state())
const hasLoaded = dataRequest.hasLoaded
const cats = ref([])
const currencies = ref([])
const methods = ref([])
const bundles = ref([])
const iconLib = ref([])

const toasts = ref([])
let toastId = 0
function toast(msg, type = 'ok') {
  const id = ++toastId
  toasts.value.push({ id, msg, type })
  setTimeout(() => { toasts.value = toasts.value.filter((x) => x.id !== id) }, 2600)
}

const PALETTE = ['#5b5bd6', '#06b6d4', '#16a34a', '#f59e0b', '#ef4444', '#a855f7', '#0ea5e9', '#ec4899']
const STATUS_COLORS = { overdue: '#ef4444', soon: '#f59e0b' }
const cur = computed(() => auth.user?.base_currency || 'CNY')
function fmt(v) { return formatMoney(v, cur.value) }
function statusOf(s) { return renewalStatus(s, { emptyStatus: 'ok' }) }
function groupStatus(events) { return groupRenewalStatus(events, { emptyStatus: '' }) }
function evColor(s) {
  const st = statusOf(s)
  if (STATUS_COLORS[st]) return STATUS_COLORS[st]
  let h = 0
  for (const ch of (s.name || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return PALETTE[h % PALETTE.length]
}
const dows = computed(() => {
  const fmt = new Intl.DateTimeFormat('zh-CN', { weekday: 'short' })
  // 2024-01-07 是周日
  return [...Array(7)].map((_, i) => fmt.format(new Date(2024, 0, 7 + i)))
})
const monthName = computed(() => {
  return new Intl.DateTimeFormat('zh-CN', { month: 'long' }).format(new Date(year.value, month.value, 1))
})

function move(d) {
  let m = month.value + d
  if (m < 0) { m = 11; year.value-- }
  else if (m > 11) { m = 0; year.value++ }
  month.value = m
}
function goToday() {
  const n = new Date()
  year.value = n.getFullYear(); month.value = n.getMonth()
}

const cells = computed(() => {
  const first = new Date(year.value, month.value, 1)
  const firstDow = first.getDay()
  const today = new Date()
  const start = new Date(year.value, month.value, 1 - firstDow)
  const dates = []
  for (let i = 0; i < 42; i++) {
    dates.push(new Date(start.getFullYear(), start.getMonth(), start.getDate() + i))
  }
  // 若最后一整行都不属于本月则去掉（保持 5~6 行紧凑）
  const visibleDates = dates.slice(35).every((d) => d.getMonth() !== month.value) ? dates.slice(0, 35) : dates
  const eventsByDate = groupRenewalEventsByDate(
    expandRenewalsInRange(subs.value, visibleDates[0], visibleDates[visibleDates.length - 1])
  )

  return visibleDates.map((d) => {
    const key = toISODate(d)
    return {
      day: d.getDate(),
      inMonth: d.getMonth() === month.value,
      key,
      isToday: today.getFullYear() === d.getFullYear() && today.getMonth() === d.getMonth() && today.getDate() === d.getDate(),
      events: eventsByDate.get(key) || []
    }
  })
})

const visibleEvents = computed(() => cells.value.filter((c) => c.inMonth).flatMap((c) => c.events))
const radarRaw = computed(() => {
  const base = {
    overdue: { key: 'overdue', label: t('dashboard.radarOverdue'), count: 0, amount: 0, missingCurrencies: new Set() },
    d3: { key: 'd3', label: t('dashboard.radar3'), count: 0, amount: 0, missingCurrencies: new Set() },
    d7: { key: 'd7', label: t('dashboard.radar7'), count: 0, amount: 0, missingCurrencies: new Set() },
    d30: { key: 'd30', label: t('dashboard.radar30'), count: 0, amount: 0, missingCurrencies: new Set() }
  }
  const events = buildRenewalRadarEvents(subs.value)
  for (const s of events) {
    const key = renewalRadarBucket(s)
    if (!key) continue
    base[key].count += 1
    const amount = baseAmountOf(s)
    if (amount === null) {
      if (s.currency) base[key].missingCurrencies.add(s.currency)
    } else {
      base[key].amount += amount
    }
  }
  return Object.values(base).map((bucket) => ({
    ...bucket,
    amountLabel: bucket.missingCurrencies.size
      ? t('calendar.radarAmountIncomplete', { currencies: [...bucket.missingCurrencies].join('、') })
      : ''
  }))
})
const radarBars = computed(() => {
  const max = Math.max(1, ...radarRaw.value.map((b) => b.count))
  return radarRaw.value.map((b) => ({ ...b, fill: Math.round((b.count / max) * 100) }))
})
const heroStatus = computed(() => {
  if (radarRaw.value.find((b) => b.key === 'overdue')?.count) return 'overdue'
  if (radarRaw.value.find((b) => b.key === 'd3')?.count || radarRaw.value.find((b) => b.key === 'd7')?.count) return 'soon'
  return 'ok'
})
const monthAmount = computed(() => visibleEvents.value.reduce((n, s) => n + amountOf(s), 0))
const missingAmountCurrencies = computed(() => [...new Set(
  visibleEvents.value
    .filter((s) => baseAmountOf(s) === null)
    .map((s) => s.currency)
    .filter(Boolean)
)].join('、'))
const calendarSummary = computed(() => {
  if (!visibleEvents.value.length) return t('calendar.monthSafe')
  if (missingAmountCurrencies.value) {
    return t('calendar.monthSummaryIncomplete', {
      n: visibleEvents.value.length,
      currencies: missingAmountCurrencies.value
    })
  }
  return t('calendar.monthSummary', { n: visibleEvents.value.length, amount: fmt(monthAmount.value) })
})

const agendaDays = computed(() => {
  const fmt = new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', weekday: 'short' })
  return cells.value
    .filter((c) => c.inMonth && c.events.length)
    .map((c) => {
      const d = new Date(year.value, month.value, c.day)
      return {
        key: `${year.value}-${month.value}-${c.day}`,
        label: fmt.format(d),
        isToday: c.isToday,
        events: c.events
      }
    })
})

let auxiliaryRequestId = 0
async function reload() {
  const requestId = ++auxiliaryRequestId
  // 核心订阅数据独立写入并立即 resolve：不让辅助元数据请求拖累 safeReload 的 busy 周期。
  await dataRequest.run(async () => (
    await api.get('/api/subscriptions', { params: { billing_type: 'recurring', active: true } })
  ).data)
  // 辅助元数据（分类/付款方式/捆绑包/币种/图标库）后台并行拉取，各自成功即写入，失败保留旧值。
  Promise.allSettled([
    api.get('/api/categories'),
    api.get('/api/payment-methods'),
    api.get('/api/bundles'),
    api.get('/api/currencies'),
    api.get('/api/icons/library')
  ]).then((aux) => {
    if (requestId !== auxiliaryRequestId) return
    const [c, m, b, cur, lib] = aux.map((r) => (r.status === 'fulfilled' ? r.value : null))
    if (c) cats.value = c.data || []
    if (m) methods.value = m.data || []
    if (b) bundles.value = b.data || []
    if (cur) currencies.value = cur.data || []
    if (lib) iconLib.value = lib.data || []
  })
}

// 订阅详情：点击的是周期展开后的 occurrence，需通过 occurrence_origin_id 回溯到原始订阅，
// 使详情/续费/编辑/删除一律基于订阅真实全貌（真实下次续费日、续费日期预览口径）。
function originOf(ev) {
  return ev.occurrence_origin_id ?? Number(String(ev.id).split(':')[0])
}
const dayEvents = ref([])
const dayEventsDate = ref('')
const showDayEvents = computed({
  get: () => dayEvents.value.length > 0,
  set: (v) => { if (!v) closeDayEvents() }
})
const dayEventsTitle = computed(() => t('calendar.dayEventsTitle', { date: dayEventsDate.value }))
function openDayEvents(cell) {
  dayEventsDate.value = cell.key
  dayEvents.value = cell.events.slice()
}
function closeDayEvents() {
  dayEvents.value = []
  dayEventsDate.value = ''
}
function openDayEventDetail(ev) {
  closeDayEvents()
  openDetail(ev)
}
const detailId = ref(null)
const showDetail = computed({
  get: () => detailId.value !== null,
  set: (v) => { if (!v) detailId.value = null }
})
function openDetail(ev) {
  detailId.value = originOf(ev)
}
function closeDetail() {
  detailId.value = null
}
function onItemKeydown(e, ev) {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    openDetail(ev)
  }
}
const detailTarget = computed(() => {
  if (detailId.value === null) return null
  return subs.value.find((s) => s.id === detailId.value) || null
})
// 订阅在操作后被删除导致 detailTarget 失联时，自动关闭弹窗。
watch(detailTarget, (s) => { if (!s) detailId.value = null })

// 详情派生字段：与雷达页/订阅账本同款解析逻辑，保证三页展示一致。
const DASH = '—'
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

// 统一汇总日历页 overlay 状态，交给引用计数式 body lock 管理。
const calendarOverlays = computed(() =>
  showDayEvents.value || showDetail.value || showForm.value || !!renewTarget.value || !!delTarget.value
)
useBodyLock(calendarOverlays, 'calendar-overlays')

onMounted(async () => {
  await reload()
})
</script>

<style scoped>
.cal-hero { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; margin-bottom: 14px;
  position: relative; overflow: hidden; background: linear-gradient(135deg, color-mix(in srgb, var(--signal-cyan) 10%, var(--surface)), var(--surface)); }
.cal-hero.overdue { background: linear-gradient(135deg, color-mix(in srgb, var(--danger) 12%, var(--surface)), var(--surface)); }
.cal-hero.soon { background: linear-gradient(135deg, color-mix(in srgb, var(--warning) 12%, var(--surface)), var(--surface)); }
.cal-hero-main { min-width: 0; }
.hero-kicker { display: flex; align-items: center; gap: 8px; font-size: 11px; text-transform: uppercase; letter-spacing: .18em; color: var(--text-soft); margin-bottom: 6px; }
.hero-kicker .signal-dot { width: 8px; height: 8px; }
.hero-kicker .signal-dot.overdue { background: var(--danger); box-shadow: 0 0 0 3px color-mix(in srgb, var(--danger) 18%, transparent), 0 0 14px color-mix(in srgb, var(--danger) 55%, transparent); }
.hero-kicker .signal-dot.soon { background: var(--warning); box-shadow: 0 0 0 3px color-mix(in srgb, var(--warning) 18%, transparent), 0 0 14px color-mix(in srgb, var(--warning) 55%, transparent); }
.title { display: flex; align-items: baseline; gap: 8px; }
.month { font-size: 24px; font-weight: 800; letter-spacing: -.03em; }
.year { font-size: 20px; font-weight: 600; }
.cal-sub { font-size: 14px; margin-top: 4px; }
.cal-ops { display: flex; flex-direction: column; gap: 10px; min-width: min(520px, 52%); }
.today-radar { display: flex; flex-direction: column; gap: 6px; }
.today-radar-label { font-size: 11px; text-align: right; letter-spacing: .04em; }
.nav { display: flex; align-items: center; justify-content: flex-end; gap: 6px; }
.navbtn { width: 34px; height: 34px; border-radius: 9px; border: 1px solid var(--border); background: var(--surface);
  font-size: 18px; color: var(--text); cursor: pointer; }
.navbtn:hover { border-color: var(--primary); color: var(--primary); }
.today-btn { padding: 7px 14px; border-radius: 9px; border: 1px solid var(--border); background: var(--surface);
  font-size: 13px; color: var(--text); cursor: pointer; min-height: 34px; }
.today-btn:hover { border-color: var(--primary); color: var(--primary); }
.cal-radar-bars { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.radar-bar { display: flex; flex-direction: column; gap: 3px; min-width: 0; border: 1px solid var(--border); border-radius: 12px;
  padding: 8px; background: color-mix(in srgb, var(--surface-2) 78%, transparent); }
.rb-count { font-size: 20px; font-weight: 800; letter-spacing: -.03em; }
.rb-label, .rb-amt { font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rb-track { height: 5px; border-radius: 999px; overflow: hidden; background: color-mix(in srgb, var(--border) 62%, transparent); }
.rb-fill { display: block; height: 100%; border-radius: 999px; }
.radar-bar.overdue { border-color: color-mix(in srgb, var(--danger) 48%, var(--border)); }
.radar-bar.overdue.active { animation: pulse-danger 2s ease-in-out infinite; }
.radar-bar.overdue .rb-count { color: var(--danger); }
.radar-bar.overdue .rb-fill { background: var(--danger); }
.radar-bar.d3 { border-color: color-mix(in srgb, var(--warning) 48%, var(--border)); }
.radar-bar.d3 .rb-count { color: var(--warning); }
.radar-bar.d3 .rb-fill { background: var(--warning); }
.radar-bar.d7 .rb-count { color: var(--primary); }
.radar-bar.d7 .rb-fill { background: var(--primary); }
.radar-bar.d30 .rb-count { color: var(--text-soft); }
.radar-bar.d30 .rb-fill { background: color-mix(in srgb, var(--primary) 42%, var(--border)); }

.cal-card { padding: 0; overflow: hidden; }
.agenda { display: none; }
.cal { display: grid; grid-template-columns: repeat(7, 1fr); }
.dow { text-align: right; font-size: 12px; font-weight: 600; color: var(--text-soft);
  padding: 12px 10px 8px; text-transform: uppercase; letter-spacing: .03em; }
.cell { min-height: 108px; border-top: 1px solid var(--border); border-left: 1px solid var(--border);
  padding: 5px 6px 7px; display: flex; flex-direction: column; background: color-mix(in srgb, var(--surface) 94%, transparent); }
.cell:nth-child(7n + 1) { border-left: none; }
.cell.active { background: linear-gradient(180deg, color-mix(in srgb, var(--signal-cyan) 4%, var(--surface)), var(--surface)); }
.cell.overdue { box-shadow: inset 0 2px 0 color-mix(in srgb, var(--danger) 72%, transparent); }
.cell.soon { box-shadow: inset 0 2px 0 color-mix(in srgb, var(--warning) 68%, transparent); }
.dnum { text-align: right; }
.num { display: inline-flex; align-items: center; justify-content: center; min-width: 24px; height: 24px;
  border-radius: 50%; font-size: 13px; padding: 0 4px; }
.cell.out .num { color: var(--text-soft); opacity: .45; }
.cell.today .num { background: color-mix(in srgb, var(--signal-cyan) 16%, transparent); color: var(--primary);
  border: 1px solid color-mix(in srgb, var(--signal-cyan) 42%, var(--border)); font-weight: 800;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--signal-cyan) 12%, transparent); }
.evs { display: flex; flex-direction: column; gap: 3px; margin-top: 3px; overflow: hidden; }
.ev { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--text);
  background: color-mix(in srgb, var(--c) 12%, transparent); border: 1px solid color-mix(in srgb, var(--c) 26%, transparent);
  border-radius: 7px; padding: 2px 5px; white-space: nowrap; overflow: hidden; }
.ev.soon { background: color-mix(in srgb, var(--warning) 12%, transparent); border-color: color-mix(in srgb, var(--warning) 28%, transparent); }
.ev.overdue { background: color-mix(in srgb, var(--danger) 12%, transparent); border-color: color-mix(in srgb, var(--danger) 30%, transparent); }
.ev-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--c); flex-shrink: 0; box-shadow: 0 0 0 2px color-mix(in srgb, var(--c) 12%, transparent); }
.ev-ico { width: 13px; height: 13px; border-radius: 3px; object-fit: contain; flex-shrink: 0; }
.ev-emoji { font-size: 12px; flex-shrink: 0; line-height: 1; }
.ev-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ev.more { width: 100%; background: transparent; border-color: transparent; color: var(--text-soft); padding: 0 5px; cursor: pointer; text-align: left; }
.ev.more:hover { color: var(--primary); }
.day-events-list { display: flex; flex-direction: column; gap: 8px; }
.day-event { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 10px; width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-2); color: var(--text); text-align: left; cursor: pointer; }
.day-event:hover { border-color: color-mix(in srgb, var(--primary) 45%, var(--border)); }
.day-event:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.day-event-ico { width: 28px; height: 28px; border-radius: 7px; object-fit: contain; }
.day-event-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.day-event-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.day-event-main .muted { font-size: 12px; }

/* 可点击的续费事件：键盘可达 + 轻量 hover，仅叠加描边不覆盖 soon/overdue 警示底色与左边框 */
.clickable { cursor: pointer; transition: background .15s ease, box-shadow .15s ease; }
.clickable:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.ev.clickable:hover { box-shadow: 0 0 0 1px color-mix(in srgb, var(--primary) 22%, transparent); }
.ag-ev.clickable:hover { box-shadow: 0 0 0 1px color-mix(in srgb, var(--primary) 22%, transparent); }

/* 详情操作条：主操作柔和强调，编辑保持中性，删除降为红色描边而非大块实心警示（与雷达页一致）。 */
.detail-action { box-shadow: none; }
.detail-action-primary { color: var(--primary); background: var(--primary-soft);
  border: 1px solid color-mix(in srgb, var(--primary) 30%, var(--border)); }
.detail-action-danger { color: var(--danger); background: transparent;
  border-color: color-mix(in srgb, var(--danger) 42%, var(--border)); }
.detail-action:hover { transform: none; box-shadow: none; }
.detail-action-primary:hover { color: var(--primary); background: color-mix(in srgb, var(--primary-soft) 72%, var(--primary) 10%); }
.detail-action-danger:hover { color: var(--danger); background: color-mix(in srgb, var(--danger) 8%, transparent); border-color: var(--danger); }

@keyframes pulse-danger { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--danger) 40%, transparent); } 50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--danger) 12%, transparent); } }
@media (prefers-reduced-motion: reduce) { .radar-bar.overdue { animation: none; } }

@media (max-width: 900px) {
  .cal-hero { flex-direction: column; }
  .cal-ops { width: 100%; min-width: 0; }
}
@media (max-width: 720px) {
  .cal-hero { gap: 14px; }
  .title { flex-wrap: wrap; }
  .cal-sub { line-height: 1.55; }
  .nav { width: 100%; justify-content: space-between; }
  .navbtn, .today-btn { min-width: 44px; height: 44px; }
  .cal-radar-bars { grid-template-columns: repeat(2, 1fr); }
  .rb-label, .rb-amt { white-space: normal; line-height: 1.25; }
  .cal { display: none; }
  .agenda { display: flex; flex-direction: column; gap: 10px; padding: 12px; }
  .ag-day { border: 1px solid var(--border); border-radius: 14px; padding: 10px; background: linear-gradient(135deg, color-mix(in srgb, var(--signal-cyan) 4%, var(--surface)), var(--surface)); }
  .ag-day.today { border-color: color-mix(in srgb, var(--signal-cyan) 42%, var(--border)); box-shadow: 0 0 0 3px color-mix(in srgb, var(--signal-cyan) 10%, transparent); }
  .ag-day.overdue { border-color: color-mix(in srgb, var(--danger) 44%, var(--border)); }
  .ag-day.soon { border-color: color-mix(in srgb, var(--warning) 42%, var(--border)); }
  .ag-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; }
  .ag-date { font-weight: 700; overflow-wrap: anywhere; }
  .ag-count { background: var(--surface-2); color: var(--text-soft); border-radius: 999px; padding: 2px 8px; font-size: 12px; }
  .ag-ev { display: grid; grid-template-columns: auto auto minmax(0, 1fr); align-items: center; gap: 8px; min-height: 44px; border-radius: 10px; padding: 6px 8px;
    border-left: 3px solid color-mix(in srgb, var(--c) 55%, transparent); background: color-mix(in srgb, var(--c) 10%, transparent); }
  .ag-ev.soon { border-left-color: var(--warning); background: color-mix(in srgb, var(--warning) 10%, transparent); }
  .ag-ev.overdue { border-left-color: var(--danger); background: color-mix(in srgb, var(--danger) 10%, transparent); }
  .ag-signal { width: 8px; height: 8px; border-radius: 999px; background: var(--c); flex-shrink: 0; box-shadow: 0 0 0 3px color-mix(in srgb, var(--c) 12%, transparent); }
  .ag-ico { width: 24px; height: 24px; border-radius: 6px; object-fit: contain; flex-shrink: 0; }
  .ag-name { min-width: 0; font-weight: 600; white-space: normal; line-height: 1.35; overflow-wrap: anywhere; }
  .ag-amt { grid-column: 3; font-size: 12px; white-space: normal; overflow-wrap: anywhere; }
  .ag-empty { padding: 28px 10px; text-align: center; }
  .month { font-size: 20px; }
  /* 详情弹窗底部三按钮：移动端横向等分紧凑排列，与雷达页一致 */
  :deep(.modal-foot) { gap: 6px; }
  :deep(.modal-foot) .btn { flex: 1 1 0; min-height: 38px; padding: 6px 8px; font-size: 13px; }
}
</style>
