<template>
  <img
    v-if="showImage"
    v-bind="$attrs"
    :src="src"
    :alt="alt || name || ''"
    decoding="async"
    @error="markFailed"
    @load="onLoad"
  />
  <span
    v-else
    v-bind="$attrs"
    class="service-icon-fallback"
    :style="{ background: bgColor }"
    :title="alt || name || fallbackText"
  >{{ fallbackText }}</span>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  src: { type: String, default: '' },
  name: { type: String, default: '' },
  fallback: { type: String, default: '' },
  alt: { type: String, default: '' }
})

const failed = ref(false)

watch(() => props.src, () => { failed.value = false })

function isImgUrl(v) {
  return typeof v === 'string' && (v.startsWith('/') || v.startsWith('http'))
}

function markFailed() {
  failed.value = true
}

function onLoad(e) {
  const img = e.target
  if (img && img.naturalWidth <= 1 && img.naturalHeight <= 1) {
    failed.value = true
  }
}

const showImage = computed(() => isImgUrl(props.src) && !failed.value)

const fallbackText = computed(() => {
  if (props.fallback && !isImgUrl(props.fallback)) return props.fallback
  const text = (props.name || props.src || '').trim()
  for (const ch of text) {
    if (/\p{Letter}|\p{Number}/u.test(ch)) return ch.toUpperCase()
  }
  return '🔖'
})

const bgColor = computed(() => {
  const text = props.name || props.src || props.fallback || 'Subly'
  let hash = 0
  for (let i = 0; i < text.length; i += 1) hash = (hash * 31 + text.charCodeAt(i)) >>> 0
  return `hsl(${hash % 360}, 72%, 45%)`
})
</script>

<style scoped>
.service-icon-fallback {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 800;
  line-height: 1;
  text-transform: uppercase;
  user-select: none;
  overflow: hidden;
}
</style>
