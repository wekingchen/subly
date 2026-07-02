<template>
  <div class="modal-mask">
    <div class="modal delete-modal" role="dialog" aria-modal="true" aria-labelledby="delete-title">
      <button class="modal-x" :aria-label="t('common.close')" @click="emit('close')">×</button>
      <div class="delete-kicker" aria-hidden="true">🗑️</div>
      <h3 id="delete-title">{{ t('sub.deleteTitle') }}</h3>
      <p class="delete-copy">{{ t('sub.deletePwdTip', { name: target?.name }) }}</p>
      <label class="delete-label" for="delete-password">{{ t('sub.pwdPh') }}</label>
      <input
        id="delete-password"
        :value="password"
        type="password"
        :placeholder="t('sub.pwdPh')"
        autocomplete="current-password"
        @input="emit('update:password', $event.target.value)"
        @keyup.enter="emit('confirm')"
      />
      <p v-if="error" class="err">{{ error }}</p>
      <div class="modal-foot">
        <button class="btn ghost" @click="emit('close')">{{ t('sub.cancel') }}</button>
        <button class="btn danger" :disabled="deleting || !password" @click="emit('confirm')">{{ t('sub.delete') }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

defineProps({
  target: { type: Object, default: null },
  password: { type: String, default: '' },
  error: { type: String, default: '' },
  deleting: { type: Boolean, default: false }
})

const emit = defineEmits(['close', 'update:password', 'confirm'])
const { t } = useI18n()
</script>

<style scoped>
.delete-modal { width: 420px; }
.delete-kicker { width: 38px; height: 38px; display: inline-flex; align-items: center; justify-content: center;
  border-radius: 14px; background: color-mix(in srgb, var(--danger) 12%, transparent); margin-bottom: 8px; font-size: 20px; }
.delete-modal h3 { margin: 0 48px 8px 0; color: var(--danger); }
.delete-copy { margin: 0; font-size: 14px; line-height: 1.6; }
.delete-label { margin-top: 14px; }
.err { color: var(--danger); font-size: 13px; margin: 8px 0 0; }
</style>
