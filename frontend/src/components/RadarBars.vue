<template>
  <div :class="['radar-bars', wrapperClass]">
    <component
      :is="bar.to ? RouterLink : itemTag"
      v-for="bar in bars"
      :key="bar.key"
      class="radar-bar"
      :class="[bar.key, { active: bar.count }]"
      :to="bar.to || undefined"
    >
      <span class="rb-count mono-data">{{ bar.count }}</span>
      <span class="rb-label">{{ bar.label }}</span>
      <MoneyText
        v-if="bar.amount !== undefined"
        class="rb-amt"
        :value="bar.amount"
        :currency="currency"
        :position="amountPosition"
        muted
      />
      <span class="rb-track"><span class="rb-fill" :style="{ width: (bar.fill || 0) + '%' }"></span></span>
    </component>
  </div>
</template>

<script setup>
import { RouterLink } from 'vue-router'
import MoneyText from './MoneyText.vue'

defineProps({
  bars: { type: Array, default: () => [] },
  currency: { type: String, default: 'CNY' },
  amountPosition: { type: String, default: 'prefix' },
  itemTag: { type: String, default: 'div' },
  wrapperClass: { type: [String, Array, Object], default: '' }
})
</script>

<style scoped>
.radar-bars { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.radar-bar {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: linear-gradient(180deg, color-mix(in srgb, var(--radar-panel-2) 86%, transparent), color-mix(in srgb, var(--card) 92%, transparent));
  color: inherit;
  text-decoration: none;
}
.rb-count { font-size: 22px; font-weight: 800; letter-spacing: -.03em; line-height: 1; }
.rb-label, .rb-amt { font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rb-track { height: 5px; border-radius: 999px; overflow: hidden; background: color-mix(in srgb, var(--border) 62%, transparent); margin-top: 2px; }
.rb-fill { display: block; height: 100%; border-radius: 999px; }
.radar-bar.overdue { border-color: color-mix(in srgb, var(--danger) 48%, var(--border)); }
.radar-bar.overdue.active { animation: pulse-danger 2s ease-in-out infinite; }
.radar-bar.overdue .rb-count { color: var(--danger); }
.radar-bar.overdue .rb-fill { background: var(--danger); }
.radar-bar.d3, .radar-bar.soon { border-color: color-mix(in srgb, var(--warning) 48%, var(--border)); }
.radar-bar.d3 .rb-count, .radar-bar.soon .rb-count { color: var(--warning); }
.radar-bar.d3 .rb-fill, .radar-bar.soon .rb-fill { background: var(--warning); }
.radar-bar.d7 .rb-count { color: var(--primary); }
.radar-bar.d7 .rb-fill { background: var(--primary); }
.radar-bar.d30 .rb-count, .radar-bar.oneTime .rb-count { color: var(--text-soft); }
.radar-bar.d30 .rb-fill { background: color-mix(in srgb, var(--primary) 42%, var(--border)); }
.radar-bar.ok .rb-count { color: var(--success); }
.radar-bar.ok .rb-fill { background: var(--success); }
.radar-bar.oneTime .rb-fill { background: color-mix(in srgb, var(--text-soft) 44%, var(--border)); }
@keyframes pulse-danger {
  0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--danger) 0%, transparent); }
  50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--danger) 16%, transparent); }
}
@media (prefers-reduced-motion: reduce) { .radar-bar.overdue.active { animation: none; } }
@media (max-width: 700px) { .radar-bars { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 520px) { .radar-bars { grid-template-columns: 1fr; } }
</style>
