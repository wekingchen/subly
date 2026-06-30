<template>
  <div>
    <div v-if="loading" class="muted">{{ t('common.loading') }}</div>
    <template v-else>
      <!-- Command Center hero -->
      <div class="hero card" :class="heroStatus">
        <div>
          <div class="hero-kicker"><SignalDot :status="heroStatus" />{{ t('dashboard.commandCenter') }}</div>
          <div class="hi">{{ t('dashboard.greeting', { name: auth.user?.username || '' }) }}</div>
          <div class="sub muted">{{ radarHero }}</div>
        </div>
        <router-link to="/subscriptions" class="btn">+ {{ t('sub.add') }}</router-link>
      </div>

      <!-- 续费雷达 -->
      <div class="card radar" v-if="radarTotal">
        <div class="radar-head">
          <h3>{{ t('dashboard.radarTitle') }}</h3>
          <router-link to="/calendar" class="more">{{ t('dashboard.viewAll') }} →</router-link>
        </div>
        <RadarBars :bars="radarBars" :currency="cur" />
      </div>

      <!-- KPI -->
      <div class="grid stats">
        <div class="card stat s1">
          <div class="badge" v-html="icon('wallet')"></div>
          <div><div class="muted">{{ t('dashboard.monthSpend') }}</div><div class="big mono-data">{{ fmt(data.month_spend) }}</div></div>
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
          <div v-for="s in data.upcoming" :key="s.id" class="line event-line" :class="statusOf(s)">
            <span class="event-signal"></span>
            <span class="l-name">
              <ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="mini-ico" />
              <span class="l-txt">{{ s.name }}</span>
            </span>
            <span class="l-right">
              <span class="tag" :class="dueClass(s)">{{ dueText(s) }}</span>
              <b class="mono-data">{{ fmt(s.amount_in_base) }}</b>
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
              <div v-for="(b, i) in breakdown.slice(0, 6)" :key="b.category" class="lg">
                <span class="dot" :style="{ background: color(i) }"></span>
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
            <div v-for="s in g.items" :key="s.id" class="cc-item" :class="statusOf(s)">
              <span class="cc-dot"></span>
              <ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="mini-ico" />
              <span class="cc-n">{{ s.name }}</span>
              <span class="cc-d">{{ s.next_renewal_date ? dueText(s) : t('sub.oneTime') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 最近订阅 -->
      <div class="card">
        <h3>{{ t('dashboard.recent') }}</h3>
        <p v-if="!data.recent.length" class="muted">{{ t('dashboard.none') }}</p>
        <div class="recent-grid">
          <div v-for="s in data.recent" :key="s.id" class="rc">
            <ServiceIcon :src="s.icon" :name="s.name" :fallback="emojiOf(s)" class="rc-ico-img" />
            <div class="rc-main"><div class="rc-n">{{ s.name }}</div>
              <div class="muted rc-a">{{ fmt(s.amount_in_base) }}</div></div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import RadarBars from '../components/RadarBars.vue'
import ServiceIcon from '../components/ServiceIcon.vue'
import SignalDot from '../components/SignalDot.vue'
import { useAuth } from '../stores/auth'
import { icon } from '../icons'
import { daysLeft } from '../utils/date'
import { amountOf, formatMoney } from '../utils/money'
import { radarBucket as renewalRadarBucket, renewalStatus } from '../utils/renewal'

const { t } = useI18n()
const auth = useAuth()
const loading = ref(true)
const data = ref({ upcoming: [], recent: [] })
const breakdown = ref([])
const expiredCount = ref(0)
const allSubs = ref([])
const cats = ref([])

const PALETTE = ['#5b5bd6', '#06b6d4', '#16a34a', '#f59e0b', '#ef4444', '#a855f7', '#0ea5e9', '#ec4899']
function color(i) { return PALETTE[i % PALETTE.length] }

const cur = computed(() => auth.user?.base_currency || 'CNY')
function fmt(v) { return formatMoney(v, cur.value) }
function isImg(v) { return typeof v === 'string' && (v.startsWith('/') || v.startsWith('http')) }
function emojiOf(s) { return s.icon && !isImg(s.icon) ? s.icon : '🔖' }
function dueText(s) {
  const d = daysLeft(s)
  if (d === null) return ''
  if (d < 0) return t('dashboard.overdue')
  return d === 0 ? t('dashboard.today') : t('dashboard.daysLeft', { n: d })
}
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
  for (const s of allSubs.value) {
    const key = renewalRadarBucket(s)
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
  breakdown.value.forEach((b, i) => {
    const start = acc; acc += b.percent
    stops.push(`${color(i)} ${start}% ${acc}%`)
  })
  if (acc < 100) stops.push(`var(--border) ${acc}% 100%`)
  return { background: `conic-gradient(${stops.join(',')})` }
})

onMounted(async () => {
  const [d, ins, exp, subs, c] = await Promise.all([
    api.get('/api/dashboard'),
    api.get('/api/reports/insights').catch(() => ({ data: { breakdown: [] } })),
    api.get('/api/reports/expired').catch(() => ({ data: [] })),
    api.get('/api/subscriptions', { params: { active: true } }).catch(() => ({ data: [] })),
    api.get('/api/categories').catch(() => ({ data: [] }))
  ])
  data.value = d.data
  breakdown.value = ins.data.breakdown || []
  expiredCount.value = (exp.data || []).length
  allSubs.value = subs.data || []
  cats.value = c.data || []
  loading.value = false
})
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
.radar-bar.overdue .rb-count { color: var(--danger); }
.radar-bar.overdue .rb-fill { background: var(--danger); }
.radar-bar.d3 { border-color: color-mix(in srgb, var(--warning) 50%, var(--border)); }
.radar-bar.d3 .rb-count { color: var(--warning); }
.radar-bar.d3 .rb-fill { background: var(--warning); }
.radar-bar.d7 .rb-count { color: var(--primary); }
.radar-bar.d7 .rb-fill { background: var(--primary); }
.radar-bar.d30 .rb-count { color: var(--text-soft); }
.radar-bar.d30 .rb-fill { background: color-mix(in srgb, var(--primary) 40%, var(--border)); }
@keyframes pulse-danger { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--danger) 40%, transparent); } 50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--danger) 12%, transparent); } }
@media (prefers-reduced-motion: reduce) { .radar-bar.overdue { animation: none; } }

.stats { grid-template-columns: repeat(4, 1fr); margin-bottom: 16px; }
.stat { display: flex; align-items: center; gap: 14px; }
.stat .badge { width: 48px; height: 48px; border-radius: 14px; display: flex; align-items: center;
  justify-content: center; flex-shrink: 0; }
.stat .badge :deep(svg) { width: 24px; height: 24px; }
.stat.s1 .badge { background: #eef0ff; color: #5b5bd6; }
.stat.s2 .badge { background: #e0f7f1; color: #0e9f6e; }
.stat.s3 .badge { background: #fff1e6; color: #f59e0b; }
.stat.s4 .badge { background: #fee2e2; color: #ef4444; }
.stat.s4.alert { border-color: var(--danger); }
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
.l-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
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
.cc-item.overdue .cc-d { color: var(--danger); font-weight: 600; }
.cc-item.soon .cc-d { color: var(--warning); font-weight: 600; }

.recent-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; }
.rc { display: flex; align-items: center; gap: 10px; padding: 10px; border: 1px solid var(--border); border-radius: 10px; }
.rc-ico { font-size: 20px; width: 26px; text-align: center; flex-shrink: 0; }
.rc-ico-img { width: 26px; height: 26px; border-radius: 7px; object-fit: contain; flex-shrink: 0;
  border: 1px solid var(--border); background: var(--surface-2); }
.rc-main { min-width: 0; }
.rc-n { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rc-a { font-size: 12px; }

@media (max-width: 980px) { .stats { grid-template-columns: 1fr 1fr; } .main { grid-template-columns: 1fr; } }
@media (max-width: 720px) {
  .stats { grid-template-columns: 1fr 1fr; }
  .radar-bars { grid-template-columns: 1fr 1fr; }
  .hero { flex-wrap: wrap; }
  .hero .btn { margin-top: 8px; }
  .stat .badge { width: 40px; height: 40px; }
  .stat .badge :deep(svg) { width: 20px; height: 20px; }
  .stat .big { font-size: 21px; }
  .donut-wrap { flex-wrap: wrap; }
}
@media (max-width: 380px) { .stats { grid-template-columns: 1fr; } }
</style>
