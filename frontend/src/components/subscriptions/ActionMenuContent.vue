<template>
  <div class="action-menu-content">
    <div class="action-head">
      <ServiceIcon
        :src="target?.icon"
        :name="target?.name"
        :fallback="target?.icon || '🔖'"
        class="action-ico"
        loading="lazy"
        decoding="async"
      />
      <div class="action-copy">
        <div :id="titleId" class="action-name">{{ target?.name }}</div>
        <div class="action-plan muted">{{ planText }}</div>
      </div>
      <button type="button" class="action-close" :aria-label="t('common.close')" @click="emit('close')">×</button>
    </div>

    <div v-if="showMove" class="action-move">
      <button type="button" class="action-move-btn" @click="emit('move', -1)">↑ {{ t('sub.moveUp') }}</button>
      <button type="button" class="action-move-btn" @click="emit('move', 1)">↓ {{ t('sub.moveDown') }}</button>
    </div>

    <button type="button" class="action-item" @click="emit('edit')">
      <span aria-hidden="true">✎</span>
      <span>{{ t('sub.edit') }}</span>
    </button>
    <button v-if="showRenew" type="button" class="action-item action-item-renew" :title="t('sub.renewHint')" @click="emit('renew')">
      <span aria-hidden="true">♻</span>
      <span class="action-item-main">
        <span>{{ t('sub.renewMark') }}</span>
        <span class="action-item-hint">{{ t('sub.renewDisclaimer') }}</span>
      </span>
    </button>
    <button type="button" class="action-item danger" @click="emit('delete')">
      <span aria-hidden="true">×</span>
      <span>{{ t('sub.delete') }}</span>
    </button>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import ServiceIcon from '../ServiceIcon.vue'

defineProps({
  target: { type: Object, default: null },
  titleId: { type: String, default: '' },
  planText: { type: String, default: '' },
  showMove: { type: Boolean, default: false },
  showRenew: { type: Boolean, default: false }
})

const emit = defineEmits(['close', 'move', 'edit', 'renew', 'delete'])
const { t } = useI18n()
</script>

<style scoped>
.action-menu-content { display: grid; gap: 4px; }
.action-head { display: flex; align-items: center; gap: 10px; padding: 8px 8px 12px; border-bottom: 1px solid var(--border); margin-bottom: 4px; }
.action-ico { width: 36px; height: 36px; border-radius: 10px; object-fit: contain; border: 1px solid var(--border); background: var(--surface-2); flex-shrink: 0; }
.action-copy { flex: 1; min-width: 0; }
.action-name { font-weight: 800; line-height: 1.25; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.action-plan { font-size: 12px; margin-top: 2px; }
.action-close { width: 36px; height: 36px; flex-shrink: 0; border: none; border-radius: 999px; background: var(--surface-2); color: var(--text-soft); cursor: pointer; font-size: 18px; line-height: 1; }
.action-close:hover { color: var(--text); }
.action-move { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; padding: 6px 0 8px; }
.action-move-btn { min-height: 42px; border: 1px solid var(--border); border-radius: 14px; background: color-mix(in srgb, var(--surface-2) 72%, transparent);
  color: var(--text-soft); font-size: 13px; font-weight: 750; cursor: pointer; }
.action-move-btn:hover { color: var(--text); border-color: color-mix(in srgb, var(--primary) 36%, var(--border)); }
.action-item { width: 100%; min-height: 48px; display: flex; align-items: center; gap: 10px; padding: 0 12px; border: none;
  border-radius: 16px; background: transparent; color: var(--text); font-size: 15px; font-weight: 700; text-align: left; cursor: pointer; }
.action-item-main { display: grid; gap: 2px; min-width: 0; }
.action-item-hint { color: var(--text-soft); font-size: 12px; font-weight: 500; line-height: 1.35; }
.action-item:hover { background: var(--surface-2); }
.action-item.danger { color: var(--danger); }
</style>
