<template>
  <div class="bar ledger-toolbar">
    <label class="search-box">
      <span class="sr-only">{{ t('sub.searchLabel') }}</span>
      <input
        :value="query"
        type="search"
        :placeholder="t('sub.searchPlaceholder')"
        @input="emit('query-change', $event.target.value)"
      />
    </label>

    <div class="seg ledger-seg" :aria-label="t('sub.typeFilter')">
      <button v-for="item in typeOptions" :key="item.value" type="button"
              :class="{ on: typeFilter === item.value }" :aria-pressed="typeFilter === item.value"
              @click="emit('type-change', item.value)">{{ t(item.label) }}</button>
    </div>

    <label class="risk-filter">
      <span>{{ t('sub.riskFilter') }}</span>
      <select :value="riskFilter" @change="emit('risk-change', $event.target.value)">
        <option value="">{{ t('sub.riskAll') }}</option>
        <option value="overdue">{{ t('sub.riskOverdue') }}</option>
        <option value="soon">{{ t('sub.riskSoon') }}</option>
        <option value="ok">{{ t('sub.riskSafe') }}</option>
      </select>
    </label>

    <span v-if="!hasActiveFilters && hasItems" class="drag-hint signal-note">
      <span aria-hidden="true">⠿</span> {{ t('sub.dragHint') }}
    </span>
    <button v-else-if="hasActiveFilters" class="btn sm ghost" type="button" @click="emit('clear-filters')">
      {{ t('sub.clearFilters') }}
    </button>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

defineProps({
  query: { type: String, default: '' },
  typeFilter: { type: String, default: '' },
  riskFilter: { type: String, default: '' },
  hasActiveFilters: { type: Boolean, default: false },
  hasItems: { type: Boolean, default: false }
})

const emit = defineEmits(['query-change', 'type-change', 'risk-change', 'clear-filters'])
const { t } = useI18n()
const typeOptions = [
  { value: '', label: 'sub.filterAll' },
  { value: 'recurring', label: 'sub.filterRecurring' },
  { value: 'one_time', label: 'sub.filterOneTime' }
]
</script>

<style scoped>
.ledger-toolbar { display: grid; grid-template-columns: minmax(180px, 1fr) auto auto auto; align-items: center; gap: 12px; margin-bottom: 16px; }
.search-box { margin: 0; }
.search-box input { margin: 0; }
.ledger-toolbar .drag-hint { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-soft); }
.signal-note { border: 1px dashed var(--border); border-radius: 999px; padding: 4px 12px; }
.risk-filter { display: flex; align-items: center; gap: 7px; margin: 0; color: var(--text-soft); font-size: 13px; white-space: nowrap; }
.risk-filter select { min-width: 108px; margin: 0; }

@media (max-width: 920px) {
  .ledger-toolbar { grid-template-columns: 1fr 1fr; }
  .search-box { grid-column: 1 / -1; }
}
@media (max-width: 720px) {
  .ledger-toolbar { grid-template-columns: 1fr; align-items: stretch; }
  .ledger-toolbar .btn { width: 100%; }
  .ledger-toolbar .drag-hint { display: none; }
  .ledger-seg { width: 100%; }
  .ledger-seg button { flex: 1 1 0; }
  .risk-filter { justify-content: space-between; }
  .risk-filter select { flex: 1; }
}
</style>
