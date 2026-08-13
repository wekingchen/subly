<template>
  <div class="toast-wrap" aria-label="操作反馈">
    <div
      v-for="toast in toasts"
      :key="toast.id"
      class="toast"
      :class="toast.type"
      :role="isError(toast) ? 'alert' : 'status'"
      :aria-live="isError(toast) ? 'assertive' : 'polite'"
    >
      {{ toast.message }}
    </div>
  </div>
</template>

<script setup>
defineProps({
  toasts: { type: Array, default: () => [] }
})

function isError(toast) {
  return toast.type === 'error' || toast.type === 'err'
}
</script>
