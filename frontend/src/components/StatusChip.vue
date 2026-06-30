<template>
  <span class="status-chip" :class="status"><slot /></span>
</template>

<script setup>
defineProps({
  status: { type: String, default: 'ok' }
})
</script>

<style scoped>
.status-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .04em;
  padding: 3px 8px;
  border-radius: 999px;
  border: 1px solid transparent;
  white-space: nowrap;
  flex-shrink: 0;
}
.status-chip.ok { background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success); }
.status-chip.soon { background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning); }
.status-chip.overdue { background: color-mix(in srgb, var(--danger) 18%, transparent); color: var(--danger); }
.status-chip.oneTime { background: color-mix(in srgb, var(--text-soft) 16%, transparent); color: var(--text-soft); }
</style>
