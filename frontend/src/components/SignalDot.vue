<template>
  <span class="signal-dot" :class="status" aria-hidden="true"></span>
</template>

<script setup>
defineProps({
  status: { type: String, default: 'ok' }
})
</script>
