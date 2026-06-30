<template>
  <span class="money-text mono-data" :class="{ muted }">{{ text }}</span>
</template>

<script setup>
import { computed } from 'vue'
import { formatMoney } from '../utils/money'

const props = defineProps({
  value: { type: [Number, String], default: 0 },
  currency: { type: String, default: 'CNY' },
  decimals: { type: Number, default: 2 },
  position: { type: String, default: 'prefix' },
  muted: { type: Boolean, default: false }
})

const text = computed(() => formatMoney(props.value, props.currency, {
  decimals: props.decimals,
  position: props.position
}))
</script>

<style scoped>
.money-text { white-space: nowrap; }
</style>
