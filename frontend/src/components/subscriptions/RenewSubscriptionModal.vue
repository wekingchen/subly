<template>
  <div class="modal-mask">
    <div
      ref="dialogRef"
      class="modal renew-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="renew-title"
      aria-describedby="renew-note"
      tabindex="-1"
    >
      <button type="button" class="modal-x" :aria-label="t('common.close')" @click="emit('close')">×</button>
      <div class="renew-kicker" aria-hidden="true">♻️</div>
      <h3 id="renew-title">{{ t(rt('renewTitle')) }}</h3>
      <p class="renew-copy">{{ t(rt('renewMsg'), { name: target?.name }) }}</p>
      <p id="renew-note" class="renew-note">{{ t(rt('renewDisclaimer')) }}</p>

      <fieldset class="renew-options">
        <legend class="renew-options-legend">{{ t(rt('renewTitle')) }}</legend>
        <label class="renew-option" :class="{ on: mode === 'today' }">
          <input type="radio" name="renew_mode" value="today" :checked="mode === 'today'" @change="emit('update:mode', 'today')" />
          <span class="renew-option-copy">
            <span class="renew-option-title">{{ t(rt('renewToday')) }}</span>
            <span class="renew-option-date mono-data">→ {{ previewToday }}</span>
          </span>
        </label>
        <label class="renew-option" :class="{ on: mode === 'due' }">
          <input type="radio" name="renew_mode" value="due" :checked="mode === 'due'" @change="emit('update:mode', 'due')" />
          <span class="renew-option-copy">
            <span class="renew-option-title">{{ t(rt('renewDue')) }}</span>
            <span class="renew-option-date mono-data">→ {{ previewDue }}</span>
          </span>
        </label>
      </fieldset>

      <div class="modal-foot">
        <button type="button" class="btn ghost" @click="emit('close')">{{ t('sub.cancel') }}</button>
        <button type="button" class="btn" :disabled="renewing" @click="emit('confirm')">{{ t(rt('renewMark')) }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useDialogFocus } from '../../composables/useDialogFocus'

const props = defineProps({
  target: { type: Object, default: null },
  mode: { type: String, default: 'today' },
  renewing: { type: Boolean, default: false },
  previewToday: { type: String, default: '' },
  previewDue: { type: String, default: '' }
})

// 保号订阅切到 sub.keepalive.* 文案前缀；普通订阅走 sub.*
const rt = (key) => (props.target?.is_keepalive ? `sub.keepalive.${key}` : `sub.${key}`)

const emit = defineEmits(['close', 'update:mode', 'confirm'])
const { t } = useI18n()
const dialogRef = ref(null)

// 续费弹窗由父级 v-if 控制挂载；关闭后把焦点还给触发按钮（卡片内联续费 / action 触发按钮）。
useDialogFocus({
  open: () => true,
  dialogRef,
  onClose: () => emit('close'),
  restoreFocus: true,
  trap: true
})
</script>

<style scoped>
.renew-modal { width: 460px; }
.renew-kicker { width: 38px; height: 38px; display: inline-flex; align-items: center; justify-content: center;
  border-radius: 14px; background: color-mix(in srgb, var(--primary-soft) 84%, transparent); margin-bottom: 8px; font-size: 20px; }
.renew-modal h3 { margin: 0 48px 8px 0; }
.renew-copy { margin: 0; font-size: 14px; line-height: 1.6; }
.renew-note { margin: 8px 0 0; color: var(--text-soft); font-size: 12px; line-height: 1.5; }
.renew-options { display: grid; gap: 10px; margin: 14px 0 0; border: none; padding: 0; min-width: 0; }
.renew-options-legend { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
.renew-option { display: flex; align-items: flex-start; gap: 10px; border: 1px solid var(--border); border-radius: 14px;
  padding: 12px; cursor: pointer; font-size: 14px; color: var(--text); width: auto; background: color-mix(in srgb, var(--surface-2) 42%, transparent);
  transition: border-color .15s ease, background .15s ease, box-shadow .15s ease; }
.renew-option.on { border-color: var(--primary); background: var(--primary-soft); box-shadow: 0 0 0 1px color-mix(in srgb, var(--primary) 12%, transparent); }
.renew-option input { width: auto; margin-top: 3px; }
.renew-option-copy { display: grid; gap: 3px; min-width: 0; }
.renew-option-title { line-height: 1.45; }
.renew-option-date { color: var(--text-soft); font-size: 12px; overflow-wrap: anywhere; }
</style>
