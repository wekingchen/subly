import { ref } from 'vue'

/**
 * 轻量确认弹窗 composable：返回响应式 state + open/close。
 * 调用方用 <AppModal v-model="state.open" :title="state.title"> 渲染，
 * onConfirm 由调用方在确认按钮上调用。
 *
 * const confirm = useConfirm()
 * function doDelete(item) {
 *   confirm.open({ title: '删除', message: `确认删除「${item.name}」？`, danger: true, onConfirm: async () => { ... } })
 * }
 */
export function useConfirm() {
  const state = ref(null)

  function open(options = {}) {
    state.value = {
      open: true,
      title: options.title || '',
      message: options.message || '',
      danger: options.danger === true,
      pending: false,
      error: '',
      onConfirm: typeof options.onConfirm === 'function' ? options.onConfirm : null
    }
  }
  function close() {
    if (state.value?.pending) return
    reset()
  }
  function reset() {
    state.value = null
  }
  async function confirm() {
    const s = state.value
    if (!s || s.pending) return
    if (!s.onConfirm) { reset(); return }
    s.pending = true
    s.error = ''
    try {
      await s.onConfirm()
      if (state.value === s) reset()
    } catch (error) {
      if (state.value !== s) return
      s.error = error?.response?.data?.detail || error?.message || '操作失败，请重试'
      s.pending = false
    }
  }

  return { state, open, close, reset, confirm }
}
