<template>
  <section class="stats" :aria-label="t('creditCards.statsLabel')">
    <article class="stat-tile card">
      <div class="stat-icon" aria-hidden="true">▣</div>
      <div class="stat-body">
        <span class="stat-label">{{ t('creditCards.activeCards') }}</span>
        <strong class="stat-value mono-data">{{ activeCount }}</strong>
        <p class="stat-desc">{{ t('creditCards.activeCardsHint', { total: totalCount }) }}</p>
      </div>
    </article>
    <article class="stat-tile card is-due">
      <div class="stat-icon" aria-hidden="true">→</div>
      <div class="stat-body">
        <span class="stat-label">{{ t('creditCards.dueSoon') }}</span>
        <strong class="stat-value mono-data">{{ dueSoonCount }}</strong>
        <p class="stat-desc" v-if="nearest">{{ t('creditCards.nearestDue', { name: nearest.card.display_name, n: nearest.days }) }}</p>
        <p class="stat-desc" v-else>{{ t('creditCards.noUpcomingDue') }}</p>
      </div>
    </article>
    <button
      type="button"
      class="stat-tile card is-interest stat-clickable"
      :aria-pressed="sortByInterestFree ? 'true' : 'false'"
      :title="t('creditCards.interestSortHint')"
      @click="$emit('toggle-interest-sort')"
    >
      <div class="stat-icon" aria-hidden="true">⚡</div>
      <div class="stat-body">
        <span class="stat-label">{{ t('creditCards.interestFreeTitle') }}</span>
        <strong class="stat-value mono-data">{{ best ? t('creditCards.interestFreeDays', { n: best.interest_free_days }) : '—' }}</strong>
        <p class="stat-desc" v-if="best">{{ t('creditCards.interestFreeBest', { name: best.display_name }) }}</p>
        <p class="stat-desc" v-else>{{ t('creditCards.interestFreeEmpty') }}</p>
      </div>
    </button>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { countUpcomingCreditCardDues, nearestCreditCardDue } from '../../utils/creditCardDates'

const props = defineProps({
  cards: { type: Array, default: () => [] },
  today: { type: [String, Date], default: () => new Date() },
  sortByInterestFree: { type: Boolean, default: false }
})

defineEmits(['toggle-interest-sort'])

const { t } = useI18n()
const activeCount = computed(() => props.cards.filter((card) => card.is_active).length)
const totalCount = computed(() => props.cards.length)
const dueSoonCount = computed(() => countUpcomingCreditCardDues(props.cards, props.today, 7))
const nearest = computed(() => nearestCreditCardDue(props.cards, props.today))
// 最长免息期只在启用卡中比较（停用卡不参与"当前"口径）。
const best = computed(() => {
  const active = props.cards.filter((card) => card.is_active && Number.isFinite(card.interest_free_days))
  if (!active.length) return null
  return active.reduce((b, card) => (card.interest_free_days > b.interest_free_days ? card : b))
})
</script>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-bottom: 18px; }
.stat-tile { display: grid; grid-template-columns: 40px minmax(0, 1fr); gap: 12px; align-items: center; min-width: 0; padding: 14px 16px; }
.stat-icon { display: flex; width: 40px; height: 40px; align-items: center; justify-content: center; border: 1px solid color-mix(in srgb, var(--signal-cyan) 38%, var(--border)); border-radius: 12px; background: color-mix(in srgb, var(--signal-cyan) 10%, var(--surface)); color: var(--primary); font-size: 18px; font-weight: 800; }
.stat-body { min-width: 0; }
.stat-label { display: block; color: var(--text-soft); font-size: 12px; font-weight: 750; letter-spacing: .06em; }
.stat-value { display: block; margin: 3px 0 0; font-size: 24px; line-height: 1; }
.stat-desc { min-width: 0; margin: 5px 0 0; color: var(--text-soft); font-size: 12px; line-height: 1.45; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.is-due .stat-icon { border-color: color-mix(in srgb, var(--warning) 42%, var(--border)); background: color-mix(in srgb, var(--warning) 10%, var(--surface)); color: var(--warning-text); }
.is-interest .stat-icon { border-color: color-mix(in srgb, var(--signal-cyan) 42%, var(--border)); background: color-mix(in srgb, var(--signal-cyan) 10%, var(--surface)); color: var(--signal-cyan); }
.stat-clickable { cursor: pointer; text-align: left; width: 100%; font: inherit; color: inherit; transition: border-color .15s ease, box-shadow .15s ease; }
.stat-clickable:hover { border-color: color-mix(in srgb, var(--signal-cyan) 68%, var(--border)); box-shadow: 0 6px 18px color-mix(in srgb, var(--signal-cyan) 14%, transparent); }
.stat-clickable:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.stat-clickable[aria-pressed="true"] { border-color: var(--signal-cyan); box-shadow: 0 0 0 1px color-mix(in srgb, var(--signal-cyan) 34%, transparent), 0 6px 18px color-mix(in srgb, var(--signal-cyan) 16%, transparent); }

/* 移动端（≤620px）：三块竖排大方块收成一张"信号面板"，内部三行紧凑条 */
@media (max-width: 620px) {
  .stats { grid-template-columns: 1fr; gap: 0; padding: 2px 14px; }
  .stat-tile { border: 0; border-radius: 0; box-shadow: none; padding: 10px 2px; }
  .stat-tile + .stat-tile { border-top: 1px solid var(--border); }
  .stat-icon { width: 30px; height: 30px; border-radius: 9px; font-size: 13px; }
  .stat-value { font-size: 17px; margin: 0; }
  .stat-body { display: flex; align-items: baseline; gap: 8px; }
  .stat-label { font-size: 11px; letter-spacing: .02em; }
  .stat-desc { display: none; }
  .stat-clickable:hover { box-shadow: none; border-color: transparent; }
  /* 激活态用 inset 阴影画左侧信号竖条：基础规则未加 !important，此处可正常覆盖 */
  .stat-clickable[aria-pressed="true"] { box-shadow: inset 3px 0 0 var(--signal-cyan); border-color: transparent; }
}
</style>
