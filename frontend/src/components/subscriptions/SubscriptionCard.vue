<template>
  <div class="card sub-card signal-card"
       :class="{ inactive: !subscription.is_active, expired: isExpired(subscription), soon: isSoon(subscription), 'drop-card': dragOver, expanded }"
       @click="onCardClick($event)"
       @dragover.prevent="emit('dragOver', { categoryKey, id: subscription.id, event: $event })"
       @drop.prevent="emit('drop', { categoryKey, id: subscription.id, event: $event })">
    <div class="status-strip" :class="statusOf"></div>
    <div class="sc-head">
      <ServiceIcon :src="subscription.icon" :name="subscription.name" :fallback="subscription.icon || '🔖'"
                   class="sc-ico" loading="lazy" decoding="async" />
      <div class="sc-title">
        <div class="sc-name">{{ subscription.name }}</div>
        <div class="muted sc-plan" v-if="subscription.plan">{{ subscription.plan }}</div>
      </div>
      <StatusChip :status="statusOf">{{ statusChip }}</StatusChip>
      <button type="button" class="card-more"
              :aria-label="`${subscription.name || navLabel}：${t('common.actions')}`"
              @click.stop="emit('openActions', { subscription, categoryKey, event: $event })">⋯</button>
      <button type="button" class="card-detail-toggle" :aria-expanded="expanded"
              :aria-controls="detailId"
              :aria-label="`${subscription.name || navLabel}：${expanded ? t('sub.collapse') : t('sub.expand')}`"
              @click.stop="emit('toggle', subscription.id)">{{ expanded ? '▾' : '▸' }}</button>
      <span v-if="sortable" class="card-grip" draggable="true" :title="t('sub.dragCard')" aria-hidden="true"
            @click.stop
            @dragstart.stop="emit('dragStart', { categoryKey, id: subscription.id, event: $event })"
            @dragend="emit('dragEnd')">⠿</span>
    </div>

    <div class="sc-signal">
      <div class="sc-amount mono-data">
        <MoneyText :value="subscription.amount" :currency="subscription.currency" position="suffix" />
        <span v-if="subscription.billing_type === 'recurring'" class="muted cycle">/ {{ cycleText }}</span>
      </div>
      <div v-if="showBaseAmount" class="sc-base-amount">
        <span class="muted">{{ t('sub.baseAmountPrefix') }}</span>
        <MoneyText :value="baseAmount" :currency="baseCurrency" position="prefix" muted />
      </div>

      <div class="sc-due" :class="statusOf" v-if="subscription.billing_type === 'recurring' && subscription.next_renewal_date">
        <span class="due mono-data">{{ subscription.next_renewal_date }}</span>
        <span class="sc-due-text">{{ dueText }}</span>
      </div>
      <div class="sc-due oneTime" v-else-if="subscription.billing_type === 'one_time'">
        <span class="sc-due-text">{{ t('sub.lifetime') }}</span>
      </div>

      <div class="sc-meter" :class="statusOf" aria-hidden="true"><span></span></div>
    </div>

    <div class="sc-quick">
      <span v-if="paymentName" class="quick-chip">{{ paymentName }}</span>
      <span v-if="subscription.billing_type === 'recurring'" class="quick-chip">🔁 {{ boolText(subscription.auto_renew) }}</span>
      <span v-if="subscription.family_members && subscription.family_members.length" class="quick-chip">👨‍👩‍👧 {{ subscription.family_members.length }}</span>
      <span v-if="bundleName" class="quick-chip">📦 {{ bundleName }}</span>
    </div>

    <SubscriptionCardDetails
      :subscription="subscription"
      :expanded="expanded"
      :detail-id="detailId"
      :category-name="categoryName"
      :base-currency="baseCurrency"
      :base-amount="baseAmount"
      :show-base-amount="showBaseAmount"
      :cycle-text="cycleText"
      :payment-name="paymentName"
      :bundle-name="bundleName"
      :family-text="familyText"
    />

    <div v-if="subscription.billing_type === 'recurring'" class="sc-acts" @click.stop>
      <button class="btn sm ghost act-btn act-renew"
              :title="t('sub.renewHint')"
              @click.stop="emit('renew', subscription)">
        <span class="act-ico" aria-hidden="true">♻</span>
        <span class="act-label">{{ t('sub.renew') }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import MoneyText from '../MoneyText.vue'
import ServiceIcon from '../ServiceIcon.vue'
import StatusChip from '../StatusChip.vue'
import SubscriptionCardDetails from './SubscriptionCardDetails.vue'
import { daysLeft } from '../../utils/date'
import { isExpired, isSoon, renewalStatus } from '../../utils/renewal'

const props = defineProps({
  subscription: { type: Object, required: true },
  categoryKey: { type: [String, Number], required: true },
  expanded: { type: Boolean, default: false },
  dragOver: { type: Boolean, default: false },
  sortable: { type: Boolean, default: false },
  detailId: { type: String, required: true },
  navLabel: { type: String, default: '' },
  baseCurrency: { type: String, default: 'CNY' },
  baseAmount: { type: [Number, String], default: 0 },
  showBaseAmount: { type: Boolean, default: false },
  categoryName: { type: String, default: '' },
  paymentName: { type: String, default: '' },
  bundleName: { type: String, default: '' },
  familyText: { type: String, default: '—' }
})

const emit = defineEmits([
  'toggle', 'openActions', 'renew',
  'cardClick', 'dragStart', 'dragOver', 'drop', 'dragEnd'
])

const { t } = useI18n()

const statusOf = computed(() => renewalStatus(props.subscription))
const cycleText = computed(() => {
  const n = props.subscription.cycle_count > 1 ? props.subscription.cycle_count + ' ' : ''
  return n + t('sub.' + props.subscription.cycle)
})
const dueText = computed(() => {
  const d = daysLeft(props.subscription)
  if (d === null) return ''
  if (d < 0) return t('sub.expiredTag')
  return d === 0 ? t('dashboard.today') : t('dashboard.daysLeft', { n: d })
})
const statusChip = computed(() => {
  const st = statusOf.value
  if (st === 'overdue') return t('sub.statusOverdue')
  if (st === 'soon') return t('sub.statusSoon') + ' · ' + Math.abs(daysLeft(props.subscription)) + 'D'
  if (st === 'oneTime') return t('sub.statusLifetime')
  return t('sub.statusSafe')
})

function boolText(v) { return v ? '✓' : '✗' }

function onCardClick(e) {
  // 点击卡片空白处展开/收起；点中按钮、链接、详情区等交互控件则交给控件自身（它们已 @click.stop）
  const target = e.target?.closest ? e.target : e.target?.parentElement
  if (target?.closest('button, a, input, select, textarea, label, summary, .sc-detail, .quick-chip')) return
  emit('cardClick', { subscription: props.subscription, event: e })
}
</script>

<style scoped>
.sub-card { display: flex; flex-direction: column; padding: 18px; cursor: pointer; position: relative; overflow: hidden;
  transition: transform .22s cubic-bezier(.2,.8,.2,1), box-shadow .22s ease, border-color .18s ease, background .18s ease; }
.sub-card:not(.expanded) { min-height: 240px; }
.sub-card:focus-visible { outline: 2px solid var(--primary); outline-offset: 3px; }
.sub-card.expanded { border-color: color-mix(in srgb, var(--primary) 45%, var(--border)); box-shadow: var(--shadow-lg);
  background: linear-gradient(180deg, color-mix(in srgb, var(--signal-cyan) 4%, var(--surface)), var(--surface)); }
.status-strip { position: absolute; left: 0; top: 0; bottom: 0; width: 4px; }
.status-strip.ok { background: var(--success); opacity: .35; }
.status-strip.soon { background: var(--warning); opacity: .85; }
.status-strip.overdue { background: var(--danger); }
.status-strip.oneTime { background: var(--text-soft); opacity: .22; }
.sub-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-lg);
  border-color: color-mix(in srgb, var(--primary) 40%, var(--border)); }
.sub-card:hover .sc-ico { transform: scale(1.05) rotate(-2deg); }
.sub-card.inactive { opacity: .55; }
.sub-card.expired { border-color: var(--danger); box-shadow: 0 0 0 1px var(--danger), var(--shadow); }
.sub-card.soon { border-color: var(--warning); box-shadow: 0 0 0 1px var(--warning), var(--shadow); }
.sub-card.drop-card { border-color: var(--primary); box-shadow: 0 0 0 2px var(--primary-soft); }
.sc-head { display: flex; align-items: center; gap: 12px; }
.sc-ico { width: 44px; height: 44px; border-radius: 12px; object-fit: contain; border: 1px solid var(--border);
  flex-shrink: 0; background: var(--surface-2); transition: transform .25s cubic-bezier(.2,.8,.2,1); }
.sc-ico.emoji { display: flex; align-items: center; justify-content: center; font-size: 26px; }
.sc-title { flex: 1; min-width: 0; }
.sc-name { font-weight: 700; font-size: 17px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sc-plan { font-size: 12px; overflow-wrap: anywhere; }
.card-grip { flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; border: none; background: transparent; color: var(--text-soft); cursor: grab;
  padding: 5px 6px; border-radius: 8px; line-height: 1; user-select: none; opacity: .35; transition: opacity .15s ease, background .12s ease, color .12s ease; }
.sub-card:hover .card-grip,
.card-grip:focus-visible { opacity: 1; }
.card-grip:hover { background: var(--surface-2); color: var(--text); }
.card-grip:active { cursor: grabbing; }
.card-more { display: inline-flex; flex-shrink: 0; align-items: center; justify-content: center; width: 32px; height: 32px;
  border: none; border-radius: 999px; background: transparent; color: var(--text-soft); cursor: pointer; font-size: 20px; line-height: 1; }
.card-more:hover { background: var(--surface-2); color: var(--text); }
.card-detail-toggle { flex-shrink: 0; border: none; background: transparent; color: var(--text-soft); cursor: pointer;
  padding: 5px 8px; border-radius: 8px; line-height: 1; font-size: 14px; }
.card-detail-toggle:hover { background: var(--surface-2); color: var(--text); }
.sc-signal { display: grid; gap: 6px; margin-top: 14px; }
.sc-amount { font-size: 28px; font-weight: 800; letter-spacing: -.02em; }
.sc-amount .cur { font-size: 15px; font-weight: 500; }
.sc-amount .cycle { font-size: 14px; font-weight: 500; }
.sc-base-amount { display: flex; align-items: baseline; gap: 6px; font-size: 12px; color: var(--text-soft); }
.sc-due { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.sc-due .due { font-weight: 700; }
.sc-due-text { font-size: 12px; color: var(--text-soft); }
.sc-due.ok .due { color: var(--text); }
.sc-due.soon .due, .sc-due.soon .sc-due-text { color: var(--warning); }
.sc-due.overdue .due, .sc-due.overdue .sc-due-text { color: var(--danger); }
.sc-due.oneTime .sc-due-text { color: var(--text-soft); font-style: italic; }
.sc-meter { height: 3px; border-radius: 999px; overflow: hidden; background: color-mix(in srgb, var(--surface-2) 48%, transparent); }
.sc-meter span { display: block; width: 54%; height: 100%; border-radius: inherit; background: color-mix(in srgb, var(--success) 62%, var(--signal-cyan)); }
.sc-meter.soon span { width: 82%; background: var(--warning); }
.sc-meter.overdue span { width: 100%; background: var(--danger); }
.sc-meter.oneTime span { width: 38%; background: color-mix(in srgb, var(--text-soft) 46%, transparent); }
.sc-quick { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.quick-chip { display: inline-flex; align-items: center; max-width: 100%; border: 1px solid var(--border); border-radius: 999px;
  padding: 3px 8px; color: var(--text-soft); background: color-mix(in srgb, var(--surface-2) 76%, transparent); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sc-acts { display: flex; gap: 8px; margin-top: auto; padding-top: 10px; border-top: 1px dashed color-mix(in srgb, var(--border) 80%, transparent); }
.sc-acts .btn { flex: 0 1 auto; }
.act-btn { display: inline-flex; align-items: center; justify-content: center; gap: 4px; }
.btn.act-renew { background: var(--primary-soft); color: var(--primary);
  border: 1px solid color-mix(in srgb, var(--primary) 24%, var(--border)); box-shadow: none; }
.btn.act-renew:hover { background: color-mix(in srgb, var(--primary-soft) 70%, var(--primary) 14%);
  border-color: color-mix(in srgb, var(--primary) 38%, var(--border)); transform: none; box-shadow: none; }
.act-ico { display: inline-flex; align-items: center; justify-content: center; line-height: 1; }
.due.soon { color: var(--warning); font-weight: 600; }
.due.overdue { color: var(--danger); font-weight: 700; }
@media (max-width: 720px) {
  .sc-head { align-items: flex-start; gap: 10px; }
  .sc-name { font-size: 16px; white-space: normal; line-height: 1.3; }
  .sc-amount { font-size: 24px; overflow-wrap: anywhere; }
  .sc-due { align-items: flex-start; flex-wrap: wrap; }
  .quick-chip { white-space: normal; line-height: 1.35; border-radius: 12px; }
  .sub-card { cursor: pointer; padding: 16px; }
  .card-grip { display: none; }
  .sc-acts { display: none; }
}
</style>
