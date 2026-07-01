<template>
  <div>
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
        <div class="nav" :aria-label="t('calendar.monthSignal')">
          <button class="navbtn" :aria-label="t('calendar.prevMonth')" @click="move(-1)">‹</button>
          <button class="today-btn" @click="goToday">{{ t('calendar.today') }}</button>
          <button class="navbtn" :aria-label="t('calendar.nextMonth')" @click="move(1)">›</button>
        </div>
        <RadarBars :bars="radarBars" :currency="cur" wrapper-class="cal-radar-bars" />
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
            <div v-for="ev in cell.events.slice(0, 3)" :key="ev.id" class="ev"
                 :class="statusOf(ev)" :style="{ '--c': evColor(ev) }" :title="ev.name">
              <span class="ev-dot"></span>
              <ServiceIcon :src="ev.icon" :name="ev.name" :fallback="emojiOf(ev)" class="ev-ico" />
              <span class="ev-name">{{ ev.name }}</span>
            </div>
            <div v-if="cell.events.length > 3" class="ev more">
              {{ t('calendar.more', { n: cell.events.length - 3 }) }}
            </div>
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
          <div v-for="ev in d.events" :key="ev.id" class="ag-ev" :class="statusOf(ev)" :style="{ '--c': evColor(ev) }">
            <span class="ag-signal"></span>
            <ServiceIcon :src="ev.icon" :name="ev.name" :fallback="emojiOf(ev)" class="ag-ico" />
            <span class="ag-name">{{ ev.name }}</span>
            <MoneyText v-if="ev.amount" class="ag-amt" :value="ev.amount" :currency="ev.currency" position="suffix" muted />
          </div>
        </div>
        <div v-if="!agendaDays.length" class="ag-empty muted">{{ t('calendar.noEvents') }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import MoneyText from '../components/MoneyText.vue'
import RadarBars from '../components/RadarBars.vue'
import ServiceIcon from '../components/ServiceIcon.vue'
import SignalDot from '../components/SignalDot.vue'
import { useAuth } from '../stores/auth'
import { toISODate } from '../utils/date'
import { amountOf, formatMoney } from '../utils/money'
import { expandRenewalsInRange, groupRenewalEventsByDate } from '../utils/recurrence'
import { groupRenewalStatus, radarBucket as renewalRadarBucket, renewalStatus } from '../utils/renewal'

const { t } = useI18n()
const auth = useAuth()
const now = new Date()
const year = ref(now.getFullYear())
const month = ref(now.getMonth())
const subs = ref([])

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
function isImg(v) { return typeof v === 'string' && (v.startsWith('/') || v.startsWith('http')) }
function emojiOf(s) { return s.icon && !isImg(s.icon) ? s.icon : '🔖' }

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
      isToday: today.getFullYear() === d.getFullYear() && today.getMonth() === d.getMonth() && today.getDate() === d.getDate(),
      events: eventsByDate.get(key) || []
    }
  })
})

const visibleEvents = computed(() => cells.value.filter((c) => c.inMonth).flatMap((c) => c.events))
const radarRaw = computed(() => {
  const base = {
    overdue: { key: 'overdue', label: t('dashboard.radarOverdue'), count: 0, amount: 0 },
    d3: { key: 'd3', label: t('dashboard.radar3'), count: 0, amount: 0 },
    d7: { key: 'd7', label: t('dashboard.radar7'), count: 0, amount: 0 },
    d30: { key: 'd30', label: t('dashboard.radar30'), count: 0, amount: 0 }
  }
  for (const s of visibleEvents.value) {
    const key = renewalRadarBucket(s)
    if (!key) continue
    base[key].count += 1
    base[key].amount += amountOf(s)
  }
  return Object.values(base)
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
const calendarSummary = computed(() => {
  if (!visibleEvents.value.length) return t('calendar.monthSafe')
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

onMounted(async () => {
  const { data } = await api.get('/api/subscriptions', { params: { billing_type: 'recurring', active: true } })
  subs.value = data
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
.ev.more { background: transparent; border-color: transparent; color: var(--text-soft); padding: 0 5px; }

@keyframes pulse-danger { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--danger) 40%, transparent); } 50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--danger) 12%, transparent); } }
@media (prefers-reduced-motion: reduce) { .radar-bar.overdue { animation: none; } }

@media (max-width: 900px) {
  .cal-hero { flex-direction: column; }
  .cal-ops { width: 100%; min-width: 0; }
}
@media (max-width: 720px) {
  .cal-hero { gap: 14px; }
  .nav { width: 100%; justify-content: space-between; }
  .navbtn, .today-btn { min-width: 44px; height: 44px; }
  .cal-radar-bars { grid-template-columns: repeat(2, 1fr); }
  .cal { display: none; }
  .agenda { display: flex; flex-direction: column; gap: 10px; padding: 12px; }
  .ag-day { border: 1px solid var(--border); border-radius: 14px; padding: 10px; background: linear-gradient(135deg, color-mix(in srgb, var(--signal-cyan) 4%, var(--surface)), var(--surface)); }
  .ag-day.today { border-color: color-mix(in srgb, var(--signal-cyan) 42%, var(--border)); box-shadow: 0 0 0 3px color-mix(in srgb, var(--signal-cyan) 10%, transparent); }
  .ag-day.overdue { border-color: color-mix(in srgb, var(--danger) 44%, var(--border)); }
  .ag-day.soon { border-color: color-mix(in srgb, var(--warning) 42%, var(--border)); }
  .ag-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .ag-date { font-weight: 700; }
  .ag-count { background: var(--surface-2); color: var(--text-soft); border-radius: 999px; padding: 2px 8px; font-size: 12px; }
  .ag-ev { display: flex; align-items: center; gap: 8px; min-height: 44px; border-radius: 10px; padding: 6px 8px;
    border-left: 3px solid color-mix(in srgb, var(--c) 55%, transparent); background: color-mix(in srgb, var(--c) 10%, transparent); }
  .ag-ev.soon { border-left-color: var(--warning); background: color-mix(in srgb, var(--warning) 10%, transparent); }
  .ag-ev.overdue { border-left-color: var(--danger); background: color-mix(in srgb, var(--danger) 10%, transparent); }
  .ag-signal { width: 8px; height: 8px; border-radius: 999px; background: var(--c); flex-shrink: 0; box-shadow: 0 0 0 3px color-mix(in srgb, var(--c) 12%, transparent); }
  .ag-ico { width: 24px; height: 24px; border-radius: 6px; object-fit: contain; flex-shrink: 0; }
  .ag-name { flex: 1; min-width: 0; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ag-amt { font-size: 12px; white-space: nowrap; }
  .ag-empty { padding: 28px 10px; text-align: center; }
  .month { font-size: 20px; }
}
</style>
