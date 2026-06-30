<template>
  <div v-if="modelValue" class="modal-mask" @click.self="close">
    <div class="modal" :style="width ? { width } : null" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <button class="modal-x" :aria-label="closeLabel" @click="close">×</button>
      <h3 v-if="title" :id="titleId">{{ title }}</h3>
      <slot />
      <div v-if="$slots.footer" class="modal-foot">
        <slot name="footer" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  width: { type: String, default: '' },
  closeLabel: { type: String, default: 'Close' }
})
const emit = defineEmits(['update:modelValue', 'close'])
const titleId = `modal-${Math.random().toString(36).slice(2)}`

function close() {
  emit('update:modelValue', false)
  emit('close')
}

watch(() => props.modelValue, (open) => {
  document.body.classList.toggle('modal-open', open)
}, { immediate: true })

onBeforeUnmount(() => document.body.classList.remove('modal-open'))
</script>
