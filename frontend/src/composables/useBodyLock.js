import { onBeforeUnmount, watch } from 'vue'

/**
 * 引用计数式 body lock：多个 overlay 来源同时申请锁时，
 * 只有全部释放后才移除 `body.modal-open`，避免互相提前解锁。
 *
 * `source` 可以是 ref / computed / getter，返回 truthy 表示需要锁 body。
 * `key` 仅用于调试来源标识，不参与去重。
 *
 * const open = ref(false)
 * useBodyLock(open, 'app-modal')
 */
const ACTIVE_CLASS = 'modal-open'
const holders = new Set()
let tokenSeq = 0

function applyLock() {
  if (typeof document === 'undefined') return
  if (holders.size > 0) document.body.classList.add(ACTIVE_CLASS)
  else document.body.classList.remove(ACTIVE_CLASS)
}

export function useBodyLock(source, key) {
  const token = Symbol(key || 'body-lock')

  function resolve() {
    return typeof source === 'function' ? source() : source.value
  }

  function sync() {
    if (resolve()) holders.add(token)
    else holders.delete(token)
    applyLock()
  }

  watch(source, sync, { immediate: true })
  onBeforeUnmount(() => {
    holders.delete(token)
    applyLock()
  })
}
