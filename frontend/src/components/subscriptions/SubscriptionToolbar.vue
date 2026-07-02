<template>
  <div class="bar ledger-toolbar">
    <div class="seg ledger-seg">
      <button :class="{ on: filter === '' }" @click="selectFilter('')">{{ t('sub.filterAll') }}</button>
      <button :class="{ on: filter === 'recurring' }" @click="selectFilter('recurring')">{{ t('sub.filterRecurring') }}</button>
      <button :class="{ on: filter === 'one_time' }" @click="selectFilter('one_time')">{{ t('sub.filterOneTime') }}</button>
    </div>
    <span v-if="!filter && hasItems" class="drag-hint signal-note">
      <span aria-hidden="true">⠿</span> {{ t('sub.dragHint') }}
    </span>
    <button v-else class="btn sm ghost" @click="selectFilter('')">{{ t('sub.filterAll') }}</button>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

defineProps({
  filter: { type: String, default: '' },
  hasItems: { type: Boolean, default: false }
})

const emit = defineEmits(['filter-change'])
const { t } = useI18n()

function selectFilter(value) {
  emit('filter-change', value)
}
</script>

<style scoped>
.ledger-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.ledger-toolbar .drag-hint { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-soft); }
.signal-note { border: 1px dashed var(--border); border-radius: 999px; padding: 4px 12px; }

@media (max-width: 720px) {
  .ledger-toolbar { align-items: stretch; }
  .ledger-toolbar .btn { width: 100%; }
  .ledger-toolbar .drag-hint { display: none; }
  .ledger-seg { width: 100%; }
  .ledger-seg button { flex: 1 1 0; }
}
</style>
