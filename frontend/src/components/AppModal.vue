<template>
  <div v-if="modelValue" class="modal-mask" @click.self="onMaskClick">
    <div
      ref="dialogRef"
      class="modal"
      :style="width ? { width } : null"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="title ? titleId : undefined"
      :aria-describedby="descriptionId || undefined"
      :aria-busy="pending ? 'true' : undefined"
      tabindex="-1"
    >
      <button class="modal-x" :aria-label="closeLabel" :disabled="pending" @click="close">×</button>
      <h3 v-if="title" :id="titleId">{{ title }}</h3>
      <slot />
      <div v-if="$slots.footer" class="modal-foot">
        <slot name="footer" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useBodyLock } from '../composables/useBodyLock'
import { useDialogFocus } from '../composables/useDialogFocus'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  width: { type: String, default: '' },
  closeLabel: { type: String, default: 'Close' },
  persistent: { type: Boolean, default: true },
  pending: { type: Boolean, default: false },
  descriptionId: { type: String, default: '' },
  initialFocus: { type: [String, Object], default: null }
})
const emit = defineEmits(['update:modelValue', 'close'])
const titleId = `modal-${Math.random().toString(36).slice(2)}`
const dialogRef = ref(null)

function close() {
  if (props.pending) return
  emit('update:modelValue', false)
  emit('close')
}
function onMaskClick() {
  // persistent 弹窗点击遮罩不关闭，避免桌面端误触丢失输入；仍可经 × / 取消 / 确认关闭。
  if (!props.persistent && !props.pending) close()
}

useBodyLock(() => props.modelValue, 'app-modal')
useDialogFocus({
  open: () => props.modelValue,
  dialogRef,
  initialFocus: () => props.initialFocus,
  onClose: close,
  restoreFocus: true,
  trap: true
})
</script>
