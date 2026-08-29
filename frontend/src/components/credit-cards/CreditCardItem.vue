<template>
  <article class="credit-card card" :class="{ inactive: !card.is_active }">
    <div class="card-head">
      <div class="card-glyph" aria-hidden="true"><span></span></div>
      <div class="card-title">
        <div class="card-name">{{ card.display_name }}</div>
        <div class="card-bank">{{ card.bank_name }} ···· {{ card.last_four }}</div>
      </div>
      <span class="status-tag" :class="card.is_active ? 'active' : 'inactive-tag'">
        {{ card.is_active ? t('creditCards.active') : t('creditCards.inactive') }}
      </span>
    </div>

    <CreditCardCycleTrack :card="card" />

    <div class="card-meta">
      <span>{{ t('creditCards.statementDayValue', { n: card.statement_day }) }}</span>
      <span>{{ t('creditCards.dueDayValue', { n: card.due_day }) }}</span>
      <span>{{ t('creditCards.remindValue', { n: card.remind_days_before }) }}</span>
    </div>

    <div class="card-actions">
      <button type="button" class="btn ghost sm" :disabled="disabled" @click="$emit('view', card)">{{ t('creditCards.viewDetails') }}</button>
      <button type="button" class="btn ghost sm" :disabled="disabled" @click="$emit('edit', card)">{{ t('creditCards.edit') }}</button>
      <button type="button" class="btn danger sm" :disabled="disabled" @click="$emit('delete', card)">{{ t('creditCards.delete') }}</button>
    </div>
  </article>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import CreditCardCycleTrack from './CreditCardCycleTrack.vue'

defineProps({
  card: { type: Object, required: true },
  disabled: { type: Boolean, default: false }
})

defineEmits(['view', 'edit', 'delete'])
const { t } = useI18n()
</script>

<style scoped>
.credit-card { position: relative; display: flex; min-width: 0; flex-direction: column; gap: 14px; overflow: hidden; }
.credit-card::before { content: ''; position: absolute; inset: 0 auto 0 0; width: 4px; background: linear-gradient(180deg, var(--signal-cyan), var(--primary)); }
.credit-card.inactive { opacity: .68; border-style: dashed; }
.credit-card.inactive::before { background: var(--text-soft); opacity: .5; }
.card-head { display: flex; min-width: 0; align-items: center; gap: 11px; }
.card-glyph { position: relative; display: flex; width: 44px; height: 34px; flex: 0 0 44px; align-items: flex-end; padding: 7px; border: 1px solid color-mix(in srgb, var(--primary) 30%, var(--border)); border-radius: 10px; background: linear-gradient(135deg, color-mix(in srgb, var(--primary) 85%, #0b1020), color-mix(in srgb, var(--signal-cyan) 52%, var(--primary))); box-shadow: 0 6px 16px color-mix(in srgb, var(--primary) 18%, transparent); }
.card-glyph::before { content: ''; position: absolute; top: 8px; left: 7px; width: 11px; height: 7px; border-radius: 3px; background: rgba(255,255,255,.78); }
.card-glyph span { width: 18px; height: 2px; border-radius: 999px; background: rgba(255,255,255,.66); }
.card-title { min-width: 0; flex: 1; }
.card-name { overflow: hidden; font-size: 16px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.card-bank { margin-top: 3px; color: var(--text-soft); font-size: 12px; overflow-wrap: anywhere; }
.status-tag { flex: 0 0 auto; padding: 4px 9px; border-radius: 999px; font-size: 11px; font-weight: 750; }
.status-tag.active { background: color-mix(in srgb, var(--success) 11%, var(--surface)); color: var(--success-text); }
.status-tag.inactive-tag { background: var(--surface-2); color: var(--text-soft); }
.card-meta { display: flex; flex-wrap: wrap; gap: 6px; }
.card-meta span { padding: 4px 8px; border: 1px solid var(--border); border-radius: 999px; background: color-mix(in srgb, var(--surface-2) 76%, transparent); color: var(--text-soft); font-size: 11px; }
.card-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: auto; padding-top: 2px; }
.card-actions .btn { flex: 1 1 auto; }
@media (hover: hover) and (pointer: fine) {
  .credit-card { transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease; }
  .credit-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-lg); }
}
@media (max-width: 420px) {
  .card-head { align-items: flex-start; flex-wrap: wrap; }
  .card-title { flex-basis: calc(100% - 56px); }
  .status-tag { margin-left: 55px; }
  .card-name { white-space: normal; }
  .card-actions { display: grid; grid-template-columns: 1fr 1fr; }
  .card-actions .btn:first-child { grid-column: 1 / -1; }
}
@media (prefers-reduced-motion: reduce) {
  .credit-card { transition: none; }
}
</style>
