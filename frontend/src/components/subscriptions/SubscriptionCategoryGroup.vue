<template>
  <div
    class="cat-group"
    :class="{ 'drop-cat': dropActive }"
    @dragover.prevent="emit('category-drag-over', { key: group.key, event: $event })"
    @drop.prevent="emit('category-drop', { key: group.key, event: $event })"
  >
    <div
      class="cat-head"
      :draggable="sortEnabled && categorySortable"
      @dragstart="emit('category-drag-start', { key: group.key, event: $event })"
      @dragend="emit('drag-end')"
    >
      <span v-if="categorySortable" class="grip">⠿</span>
      <span class="cat-ico">{{ group.icon }}</span>
      <span class="cat-name">{{ group.name }}</span>
      <span class="cat-count">{{ group.items.length }}</span>
      <span v-if="sortEnabled && categorySortable" class="mobile-sort">
        <button class="btn sm ghost" @click.stop="emit('move-category', { key: group.key, dir: -1 })" :aria-label="t('sub.moveUp')">↑</button>
        <button class="btn sm ghost" @click.stop="emit('move-category', { key: group.key, dir: 1 })" :aria-label="t('sub.moveDown')">↓</button>
      </span>
    </div>

    <div class="sub-grid">
      <SubscriptionCard
        v-for="s in group.items"
        :key="s.id"
        :subscription="s"
        :category-key="group.key"
        :expanded="s.id === expandedId"
        :drag-over="dragOverSubId === s.id"
        :sortable="sortEnabled"
        :detail-id="detailId(s.id)"
        :nav-label="navLabel"
        :base-currency="baseCurrency"
        :base-amount="baseAmount(s)"
        :show-base-amount="showBaseAmount(s)"
        :category-name="categoryName(s)"
        :payment-name="paymentName(s)"
        :bundle-name="bundleName(s)"
        :family-text="familyText(s)"
        @toggle="emit('toggle', $event)"
        @card-click="emit('card-click', $event)"
        @open-actions="emit('open-actions', $event)"
        @renew="emit('renew', $event)"
        @drag-start="emit('card-drag-start', $event)"
        @drag-over="forwardCardDragOver"
        @drop="forwardCardDrop"
        @drag-end="emit('drag-end')"
      />
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import SubscriptionCard from './SubscriptionCard.vue'

defineProps({
  group: { type: Object, required: true },
  sortEnabled: { type: Boolean, default: false },
  categorySortable: { type: Boolean, default: false },
  dropActive: { type: Boolean, default: false },
  dragOverSubId: { type: [String, Number], default: null },
  expandedId: { type: [String, Number], default: null },
  navLabel: { type: String, default: '' },
  baseCurrency: { type: String, default: 'CNY' },
  baseAmount: { type: Function, required: true },
  showBaseAmount: { type: Function, required: true },
  categoryName: { type: Function, required: true },
  paymentName: { type: Function, required: true },
  bundleName: { type: Function, required: true },
  familyText: { type: Function, required: true }
})

const emit = defineEmits([
  'move-category',
  'category-drag-start',
  'category-drag-over',
  'category-drop',
  'toggle',
  'card-click',
  'open-actions',
  'renew',
  'card-drag-start',
  'card-drag-over',
  'card-drop',
  'drag-end'
])
const { t } = useI18n()

function detailId(id) {
  return `sub-detail-${id}`
}

function forwardCardDragOver(payload) {
  emit('card-drag-over', payload)
}

function forwardCardDrop(payload) {
  emit('card-drop', payload)
}
</script>

<style scoped>
.cat-group { margin-bottom: 22px; border-radius: 14px; transition: outline .12s; outline: 2px dashed transparent; }
.cat-group.drop-cat { outline-color: var(--primary); outline-offset: 4px; }
.cat-head { display: flex; align-items: center; gap: 8px; padding: 6px 4px 12px; cursor: grab; }
.cat-head .grip { color: var(--text-soft); cursor: grab; }
.cat-ico { font-size: 18px; }
.cat-name { font-weight: 700; font-size: 16px; }
.cat-count { background: var(--surface-2); color: var(--text-soft); border-radius: 20px;
  padding: 1px 9px; font-size: 12px; }
.mobile-sort { display: none; gap: 6px; }
.sub-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
@media (max-width: 720px) {
  .sub-grid { grid-template-columns: 1fr; }
  .cat-head { cursor: default; flex-wrap: wrap; }
  .cat-head .grip { display: none; }
  .mobile-sort { display: inline-flex; margin-left: auto; }
}
</style>
