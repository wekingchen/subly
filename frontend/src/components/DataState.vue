<template>
  <section
    class="data-state"
    :class="[`is-${state}`, { compact }]"
    :aria-busy="state === 'loading' || state === 'refreshing'"
    :aria-live="state === 'refreshing' || state === 'stale' ? 'polite' : 'off'"
    :data-state="state"
    :data-trust="trust"
  >
    <template v-if="state === 'loading'">
      <span class="data-state-spinner" aria-hidden="true"></span>
      <strong>{{ loadingTitle }}</strong>
      <span v-if="loadingDescription" class="data-state-description">{{ loadingDescription }}</span>
    </template>

    <template v-else-if="state === 'error'">
      <strong>{{ errorTitle }}</strong>
      <span v-if="errorDescription" class="data-state-description">{{ errorDescription }}</span>
      <button v-if="retryable" class="btn sm ghost" type="button" @click="$emit('retry')">{{ retryLabel }}</button>
    </template>

    <template v-else-if="state === 'empty'">
      <strong>{{ emptyTitle }}</strong>
      <span v-if="emptyDescription" class="data-state-description">{{ emptyDescription }}</span>
      <slot name="empty-action" />
    </template>

    <template v-else-if="state === 'refreshing'">
      <span class="data-state-spinner" aria-hidden="true"></span>
      <span>{{ refreshingLabel }}</span>
    </template>

    <template v-else-if="state === 'stale'">
      <strong>{{ staleTitle }}</strong>
      <span v-if="staleDescription" class="data-state-description">{{ staleDescription }}</span>
      <button v-if="retryable" class="btn sm ghost" type="button" @click="$emit('retry')">{{ retryLabel }}</button>
    </template>
  </section>
</template>

<script setup>
defineProps({
  state: {
    type: String,
    required: true,
    validator: (value) => ['loading', 'error', 'empty', 'refreshing', 'stale'].includes(value)
  },
  trust: { type: String, default: 'unknown' },
  loadingTitle: { type: String, default: '正在加载数据…' },
  loadingDescription: { type: String, default: '' },
  errorTitle: { type: String, default: '数据加载失败' },
  errorDescription: { type: String, default: '请检查网络后重试。' },
  emptyTitle: { type: String, default: '暂无数据' },
  emptyDescription: { type: String, default: '' },
  refreshingLabel: { type: String, default: '正在刷新…' },
  staleTitle: { type: String, default: '当前显示的是上次成功加载的数据' },
  staleDescription: { type: String, default: '刷新失败，你可以稍后重试。' },
  retryLabel: { type: String, default: '重试' },
  retryable: { type: Boolean, default: true },
  compact: { type: Boolean, default: false }
})

defineEmits(['retry'])
</script>

<style scoped>
.data-state {
  display: flex;
  min-height: 160px;
  padding: 24px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--surface) 90%, transparent);
  color: var(--text-soft);
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 8px;
  text-align: center;
}
.data-state.compact {
  min-height: auto;
  padding: 10px 12px;
  flex-direction: row;
  justify-content: flex-start;
  text-align: left;
}
.data-state.is-refreshing {
  border-style: solid;
}
.data-state.is-stale,
.data-state.is-error {
  border-color: color-mix(in srgb, var(--warning) 55%, var(--border));
  background: color-mix(in srgb, var(--warning) 8%, var(--surface));
}
.data-state.is-error {
  border-color: color-mix(in srgb, var(--danger) 55%, var(--border));
  background: color-mix(in srgb, var(--danger) 7%, var(--surface));
}
.data-state strong {
  color: var(--text);
}
.data-state-description {
  max-width: 52ch;
  font-size: 13px;
}
.data-state-spinner {
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  border: 2px solid color-mix(in srgb, var(--primary) 24%, transparent);
  border-top-color: var(--primary);
  border-radius: 999px;
  animation: data-state-spin .75s linear infinite;
}
@keyframes data-state-spin {
  to { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .data-state-spinner { animation: none; }
}
</style>
