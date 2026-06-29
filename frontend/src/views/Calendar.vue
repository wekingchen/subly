<template>
  <div>
    <div class="head">
      <div class="title">
        <span class="month">{{ monthName }}</span>
        <span class="year muted">{{ year }}</span>
      </div>
      <div class="nav">
        <button class="navbtn" :aria-label="t('calendar.prevMonth')" @click="move(-1)">‹</button>
        <button class="today-btn" @click="goToday">{{ t('calendar.today') }}</button>
        <button class="navbtn" :aria-label="t('calendar.nextMonth')" @click="move(1)">›</button>
      </div>
    </div>

    <div class="card cal-card">
      <!-- 桌面：7 列月历 -->
      <div class="cal">
        <div class="dow" v-for="d in dows" :key="d">{{ d }}</div>
        <div v-for="(cell, i) in cells" :key="i" class="cell"
             :class="{ out: !cell.inMonth, today: cell.isToday }">
          <div class="dnum"><span class="num">{{ cell.day }}</span></div>
          <div class="evs">
            <div v-for="ev in cell.events.slice(0, 3)" :key="ev.id" class="ev"
                 :style="{ '--c': evColor(ev) }" :title="ev.name">
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
        <div v-for="d in agendaDays" :key="d.key" class="ag-day" :class="{ today: d.isToday }">
          <div class="ag-head">
            <span class="ag-date">{{ d.label }}</span>
            <span class="ag-count">{{ d.events.length }}</span>
          </div>
          <div v-for="ev in d.events" :key="ev.id" class="ag-ev" :style="{ '--c': evColor(ev) }">
            <ServiceIcon :src="ev.icon" :name="ev.name" :fallback="emojiOf(ev)" class="ag-ico" />
            <span class="ag-name">{{ ev.name }}</span>
            <span v-if="ev.amount" class="ag-amt muted">{{ ev.amount }} {{ ev.currency }}</span>
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
import ServiceIcon from '../components/ServiceIcon.vue'

const { t, locale } = useI18n()
const now = new Date()
const year = ref(now.getFullYear())
const month = ref(now.getMonth())
const subs = ref([])

const PALETTE = ['#5b5bd6', '#06b6d4', '#16a34a', '#f59e0b', '#ef4444', '#a855f7', '#0ea5e9', '#ec4899']
const STATUS_COLORS = { overdue: '#ef4444', soon: '#f59e0b' }
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
  const fmt = new Intl.DateTimeFormat(locale.value === 'zh' ? 'zh-CN' : locale.value, { weekday: 'short' })
  // 2024-01-07 是周日
  return [...Array(7)].map((_, i) => fmt.format(new Date(2024, 0, 7 + i)))
})
const monthName = computed(() => {
  const loc = locale.value === 'zh' ? 'zh-CN' : locale.value
  return new Intl.DateTimeFormat(loc, { month: 'long' }).format(new Date(year.value, month.value, 1))
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
  const arr = []
  for (let i = 0; i < 42; i++) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)
    const events = subs.value.filter((s) => {
      if (!s.next_renewal_date || s.show_in_calendar === false) return false
      const dt = new Date(s.next_renewal_date)
      return dt.getFullYear() === d.getFullYear() && dt.getMonth() === d.getMonth() && dt.getDate() === d.getDate()
    })
    arr.push({
      day: d.getDate(),
      inMonth: d.getMonth() === month.value,
      isToday: today.getFullYear() === d.getFullYear() && today.getMonth() === d.getMonth() && today.getDate() === d.getDate(),
      events
    })
  }
  // 若最后一整行都不属于本月则去掉（保持 5~6 行紧凑）
  if (arr.slice(35).every((c) => !c.inMonth)) return arr.slice(0, 35)
  return arr
})

const agendaDays = computed(() => {
  const loc = locale.value === 'zh' ? 'zh-CN' : locale.value
  const fmt = new Intl.DateTimeFormat(loc, { month: 'short', day: 'numeric', weekday: 'short' })
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
.head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.title { display: flex; align-items: baseline; gap: 8px; }
.month { font-size: 24px; font-weight: 700; letter-spacing: -.02em; }
.year { font-size: 20px; font-weight: 500; }
.nav { display: flex; align-items: center; gap: 6px; }
.navbtn { width: 34px; height: 34px; border-radius: 9px; border: 1px solid var(--border); background: var(--surface);
  font-size: 18px; color: var(--text); cursor: pointer; }
.navbtn:hover { border-color: var(--primary); color: var(--primary); }
.today-btn { padding: 7px 14px; border-radius: 9px; border: 1px solid var(--border); background: var(--surface);
  font-size: 13px; color: var(--text); cursor: pointer; min-height: 34px; }
.today-btn:hover { border-color: var(--primary); color: var(--primary); }

.cal-card { padding: 0; overflow: hidden; }
.agenda { display: none; }
.cal { display: grid; grid-template-columns: repeat(7, 1fr); }
.dow { text-align: right; font-size: 12px; font-weight: 600; color: var(--text-soft);
  padding: 12px 10px 8px; text-transform: uppercase; letter-spacing: .03em; }
.cell { min-height: 104px; border-top: 1px solid var(--border); border-left: 1px solid var(--border);
  padding: 4px 5px 6px; display: flex; flex-direction: column; }
.cell:nth-child(7n + 1) { border-left: none; }
.dnum { text-align: right; }
.num { display: inline-flex; align-items: center; justify-content: center; min-width: 24px; height: 24px;
  border-radius: 50%; font-size: 13px; padding: 0 4px; }
.cell.out .num { color: var(--text-soft); opacity: .45; }
.cell.today .num { background: var(--danger); color: #fff; font-weight: 600; }
.evs { display: flex; flex-direction: column; gap: 3px; margin-top: 2px; overflow: hidden; }
.ev { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--text);
  background: color-mix(in srgb, var(--c) 14%, transparent); border-radius: 5px; padding: 2px 5px;
  white-space: nowrap; overflow: hidden; }
.ev-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--c); flex-shrink: 0; }
.ev-ico { width: 13px; height: 13px; border-radius: 3px; object-fit: contain; flex-shrink: 0; }
.ev-emoji { font-size: 12px; flex-shrink: 0; line-height: 1; }
.ev-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ev.more { background: transparent; color: var(--text-soft); padding: 0 5px; }

@media (max-width: 720px) {
  .head { flex-wrap: wrap; gap: 10px; }
  .nav { width: 100%; justify-content: space-between; }
  .navbtn, .today-btn { min-width: 44px; height: 44px; }
  .cal { display: none; }
  .agenda { display: flex; flex-direction: column; gap: 10px; padding: 12px; }
  .ag-day { border: 1px solid var(--border); border-radius: 12px; padding: 10px; background: var(--surface); }
  .ag-day.today { border-color: var(--danger); }
  .ag-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .ag-date { font-weight: 700; }
  .ag-count { background: var(--surface-2); color: var(--text-soft); border-radius: 999px; padding: 2px 8px; font-size: 12px; }
  .ag-ev { display: flex; align-items: center; gap: 8px; min-height: 44px; border-radius: 10px; padding: 6px 8px;
    background: color-mix(in srgb, var(--c) 12%, transparent); }
  .ag-ico { width: 24px; height: 24px; border-radius: 6px; object-fit: contain; flex-shrink: 0; }
  .ag-name { flex: 1; min-width: 0; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ag-amt { font-size: 12px; white-space: nowrap; }
  .ag-empty { padding: 28px 10px; text-align: center; }
  .month { font-size: 20px; }
}
</style>

