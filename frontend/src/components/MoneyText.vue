<template>
  <span class="money-text mono-data" :class="{ muted }" :style="currencySize ? { '--money-currency-size': currencySize } : null">
    <template v-if="splitCurrency">
      <span v-if="position === 'suffix'" class="amt">{{ parts.amountPart }}</span>
      <span v-if="parts.currencyPart" class="cur">{{ parts.currencyPart }}{{ space ? ' ' : '' }}</span>
      <span v-if="position !== 'suffix'" class="amt">{{ parts.amountPart }}</span>
    </template>
    <template v-else>{{ text }}</template>
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { formatMoney, splitMoney } from '../utils/money'

const props = defineProps({
  value: { type: [Number, String], default: 0 },
  currency: { type: String, default: 'CNY' },
  decimals: { type: Number, default: 2 },
  position: { type: String, default: 'prefix' },
  muted: { type: Boolean, default: false },
  // 开启币种小字号层级：传 CSS 字号字符串（如 '15px'）即拆分币种/金额，留空则保持单字符串现状
  currencySize: { type: String, default: '' }
})

// 关闭路径：与改造前完全一致的单字符串
const text = computed(() => formatMoney(props.value, props.currency, {
  decimals: props.decimals,
  position: props.position
}))

// 开启路径：用 splitMoney 拆段，space 与 formatMoney 默认一致
const splitCurrency = computed(() => !!props.currencySize)
const space = computed(() => true)
const parts = computed(() => splitMoney(props.value, props.currency, {
  decimals: props.decimals,
  position: props.position
}))
</script>

<style scoped>
.money-text { white-space: nowrap; }
.cur { font-size: var(--money-currency-size, 1em); }
</style>
