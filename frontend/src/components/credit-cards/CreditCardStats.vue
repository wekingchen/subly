<template>
  <section class="stats" :aria-label="t('creditCards.statsLabel')">
    <article class="stat-tile card">
      <div class="stat-icon" aria-hidden="true">▣</div>
      <div>
        <span class="stat-label">{{ t('creditCards.activeCards') }}</span>
        <strong class="stat-value mono-data">{{ activeCount }}</strong>
        <p>{{ t('creditCards.activeCardsHint', { total: totalCount }) }}</p>
      </div>
    </article>
    <article class="stat-tile card is-due">
      <div class="stat-icon" aria-hidden="true">→</div>
      <div>
        <span class="stat-label">{{ t('creditCards.dueSoon') }}</span>
        <strong class="stat-value mono-data">{{ dueSoonCount }}</strong>
        <p v-if="nearest">{{ t('creditCards.nearestDue', { name: nearest.card.display_name, n: nearest.days }) }}</p>
        <p v-else>{{ t('creditCards.noUpcomingDue') }}</p>
      </div>
    </article>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { countUpcomingCreditCardDues, nearestCreditCardDue } from '../../utils/creditCardDates'

const props = defineProps({
  cards: { type: Array, default: () => [] },
  today: { type: [String, Date], default: () => new Date() }
})

const { t } = useI18n()
const activeCount = computed(() => props.cards.filter((card) => card.is_active).length)
const totalCount = computed(() => props.cards.length)
const dueSoonCount = computed(() => countUpcomingCreditCardDues(props.cards, props.today, 7))
const nearest = computed(() => nearestCreditCardDue(props.cards, props.today))
</script>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-bottom: 18px; }
.stat-tile { display: grid; grid-template-columns: 44px minmax(0, 1fr); gap: 14px; align-items: center; min-width: 0; padding: 17px 18px; }
.stat-icon { display: flex; width: 44px; height: 44px; align-items: center; justify-content: center; border: 1px solid color-mix(in srgb, var(--signal-cyan) 38%, var(--border)); border-radius: 14px; background: color-mix(in srgb, var(--signal-cyan) 10%, var(--surface)); color: var(--primary); font-size: 20px; font-weight: 800; }
.is-due .stat-icon { border-color: color-mix(in srgb, var(--warning) 42%, var(--border)); background: color-mix(in srgb, var(--warning) 10%, var(--surface)); color: var(--warning-text); }
.stat-label { color: var(--text-soft); font-size: 12px; font-weight: 750; letter-spacing: .06em; }
.stat-value { display: block; margin: 2px 0; font-size: 28px; line-height: 1; }
.stat-tile p { min-width: 0; margin: 5px 0 0; color: var(--text-soft); font-size: 12px; line-height: 1.45; overflow-wrap: anywhere; }
@media (max-width: 620px) {
  .stats { grid-template-columns: 1fr; gap: 10px; }
  .stat-tile { padding: 14px; }
}
</style>
