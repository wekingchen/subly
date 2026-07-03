<template>
  <div class="modal-mask">
    <div
      ref="dialogRef"
      class="modal delete-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-title"
      tabindex="-1"
    >
      <button type="button" class="modal-x" :aria-label="t('common.close')" @click="emit('close')">×</button>
      <div class="delete-kicker" aria-hidden="true">🗑️</div>
      <h3 id="delete-title">{{ t('sub.deleteTitle') }}</h3>
      <p class="delete-copy">{{ t('sub.deletePwdTip', { name: target?.name }) }}</p>
      <label class="delete-label" for="delete-password">{{ t('sub.pwdPh') }}</label>
      <input
        id="delete-password"
        ref="passwordInputRef"
        :value="password"
        type="password"
        name="delete_password"
        :placeholder="t('sub.pwdPh')"
        autocomplete="current-password"
        :aria-invalid="!!error"
        :aria-describedby="error ? 'delete-password-error' : undefined"
        @input="emit('update:password', $event.target.value)"
        @keyup.enter="emit('confirm')"
      />
      <p v-if="error" id="delete-password-error" class="err" role="alert">{{ error }}</p>
      <div class="modal-foot">
        <button type="button" class="btn ghost" @click="emit('close')">{{ t('sub.cancel') }}</button>
        <button type="button" class="btn danger" :disabled="deleting || !password" @click="emit('confirm')">{{ t('sub.delete') }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useDialogFocus } from '../../composables/useDialogFocus'

defineProps({
  target: { type: Object, default: null },
  password: { type: String, default: '' },
  error: { type: String, default: '' },
  deleting: { type: Boolean, default: false }
})

const emit = defineEmits(['close', 'update:password', 'confirm'])
const { t } = useI18n()
const dialogRef = ref(null)
const passwordInputRef = ref(null)

// 删除弹窗由父级 v-if 控制挂载；关闭后把焦点还给触发按钮（action 触发按钮）。
useDialogFocus({
  open: () => true,
  dialogRef,
  initialFocus: passwordInputRef,
  onClose: () => emit('close'),
  restoreFocus: true,
  trap: true
})
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
