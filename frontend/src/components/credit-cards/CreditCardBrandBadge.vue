<template>
  <span
    class="bank-badge"
    :style="brand && !logoUrl ? { background: `linear-gradient(135deg, ${brand.color}, color-mix(in srgb, ${brand.color} 62%, #0b1020))` } : null"
    role="img"
    :aria-label="brand ? brand.name : '发卡银行'"
  >
    <img
      v-if="logoUrl"
      :src="logoUrl"
      :alt="brand ? brand.name : '银行图标'"
      loading="lazy"
      @error="onLogoError"
    />
    <template v-else>{{ brand ? brand.short : '·' }}</template>
  </span>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { matchBankBrand } from '../../utils/creditCardBanks'

// 银行徽标：优先展示官方 logo（复用内置图标库 /api/icons/library/{slug}，
// 后端从银行官网 favicon 抓取、消毒并缓存到本地）；抓取失败或未收录时
// 回退品牌色字标（brand.short），不阻塞渲染。
const props = defineProps({
  bankName: { type: String, default: '' }
})

const brand = computed(() => matchBankBrand(props.bankName))
const logoUrl = ref('')
const logoFailed = ref(false)

watch(
  () => [props.bankName, brand.value?.key],
  ([name]) => {
    logoUrl.value = ''
    logoFailed.value = false
    if (!brand.value || !brand.value.slug || !name) return
    // 内置服务库 slug 规则：domain 的点替换为下划线（如 cmbchina.com → cmbchina_com）。
    logoUrl.value = `/api/icons/library/${brand.value.slug}`
  },
  { immediate: true }
)

function onLogoError() {
  logoFailed.value = true
  logoUrl.value = ''
}
</script>

<style scoped>
.bank-badge {
  display: inline-flex;
  width: 100%;
  height: 100%;
  align-items: center;
  justify-content: center;
  border-radius: inherit;
  overflow: hidden;
  color: #fff;
  font-size: 15px;
  font-weight: 800;
  background: linear-gradient(135deg, color-mix(in srgb, var(--primary) 85%, #0b1020), color-mix(in srgb, var(--signal-cyan) 52%, var(--primary)));
}
.bank-badge img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #fff;
}
</style>
