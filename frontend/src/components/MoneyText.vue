<template>
  <span class="money-text mono-data" :class="{ muted }" :style="splitCurrency && currencySize ? { '--money-currency-size': currencySize } : null">
    <template v-if="splitCurrency && parts.currencyPart">
      <template v-if="position === 'suffix'">
        <span class="amt">{{ parts.amountPart }}</span> <span class="cur">{{ parts.currencyPart }}</span>
      </template>
      <template v-else>
        <span class="cur">{{ parts.currencyPart }}</span> <span class="amt">{{ parts.amountPart }}</span>
      </template>
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
  // 是否拆分币种/金额为独立 span（便于差异化样式）
  splitCurrency: { type: Boolean, default: false },
  // 拆分后币种的 CSS 字号（如 '15px'）；仅 splitCurrency 开启时生效
  currencySize: { type: String, default: '' }
})

// 关闭路径：与改造前完全一致的单字符串
const text = computed(() => formatMoney(props.value, props.currency, {
  decimals: props.decimals,
  position: props.position
}))

// 开启路径：用 splitMoney 拆段，空格作为独立文本节点放在两 span 之间（与 formatMoney 一致，无尾随空格）
const parts = computed(() => splitMoney(props.value, props.currency, {
  decimals: props.decimals,
  position: props.position
}))
</script>

<style scoped>
.money-text { white-space: nowrap; }
.cur { font-size: var(--money-currency-size, 1em); }
</style>
