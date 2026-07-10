import { nextTick, onBeforeUnmount, watch } from 'vue'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'textarea',
  'select',
  'input:not([type="hidden"])',
  '[tabindex]:not([tabindex="-1"])'
].join(',')

// 模块级 active dialog 栈：Escape / Tab 只作用于栈顶，避免嵌套弹窗双触发。
const stack = []

function topOfStack() {
  return stack.length ? stack[stack.length - 1] : null
}

function toEl(target) {
  if (!target) return null
  if (typeof target === 'string') return document.querySelector(target)
  // Vue ref (.value) 或直接 DOM 元素
  if (target.value && target.value.nodeType) return target.value
  if (target.nodeType) return target
  return null
}

function isVisible(el) {
  if (el.hasAttribute('disabled')) return false
  if (el === document.activeElement) return true
  // offsetParent 为 null 通常意味着元素不可见（display:none / 隐藏祖先）。
  return el.offsetParent !== null
}

function queryFocusable(root) {
  if (!root) return []
  return Array.from(root.querySelectorAll(FOCUSABLE)).filter(isVisible)
}

/**
 * 轻量 dialog 焦点管理：初始聚焦、Escape 关闭、Tab 在 dialog 内环绕、可选恢复焦点。
 * 不引入第三方 focus-trap 库，只覆盖订阅弹窗需要的最小行为。
 *
 * useDialogFocus({
 *   open,           // ref/computed/getter，dialog 是否打开
 *   dialogRef,      // dialog 根元素 ref
 *   initialFocus,   // 可选：ref/selector/元素，打开后聚焦目标；找不到则聚焦 dialog
 *   onClose,        // 可选：Escape 时回调
 *   restoreFocus,   // 默认 true，关闭后把焦点还给打开前元素
 *   trap            // 默认 true，是否做 Tab 环绕
 * })
 */
export function useDialogFocus({
  open,
  dialogRef,
  initialFocus = null,
  onClose = null,
  restoreFocus = true,
  trap = true
}) {
  const entry = { open, dialogRef, initialFocus, onClose, trap, prevActive: null, active: false }

  function onKeydown(e) {
    const top = topOfStack()
    if (top !== entry) return
    if (e.key === 'Escape') {
      if (typeof onClose === 'function') {
        e.preventDefault()
        onClose()
      }
      return
    }
    if (trap && e.key === 'Tab') {
      const dialog = toEl(dialogRef)
      if (!dialog) return
      const items = queryFocusable(dialog)
      if (!items.length) {
        e.preventDefault()
        dialog.focus()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      const inside = dialog.contains(active)
      if (e.shiftKey) {
        if (active === first || !inside) {
          e.preventDefault()
          last.focus()
        }
      } else if (active === last || !inside) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  function enter() {
    if (entry.active) return
    entry.active = true
    entry.prevActive = typeof document !== 'undefined' ? document.activeElement : null
    stack.push(entry)
    nextTick(() => {
      if (!entry.active) return
      const dialog = toEl(dialogRef)
      if (!dialog) return
      const target = toEl(initialFocus) || dialog
      target.focus?.()
    })
  }

  function leave() {
    if (!entry.active) return
    entry.active = false
    const idx = stack.indexOf(entry)
    if (idx !== -1) stack.splice(idx, 1)
    const prev = entry.prevActive
    entry.prevActive = null
    if (restoreFocus && prev && typeof prev.focus === 'function' && prev.isConnected) {
      nextTick(() => prev.focus())
    }
  }

  watch(open, (isOpen, wasOpen) => {
    if (isOpen && !wasOpen) enter()
    else if (!isOpen && wasOpen) leave()
  }, { immediate: true })

  function bind() {
    if (typeof window !== 'undefined') window.addEventListener('keydown', onKeydown, true)
  }
  function unbind() {
    if (typeof window !== 'undefined') window.removeEventListener('keydown', onKeydown, true)
  }

  bind()
  onBeforeUnmount(() => {
    unbind()
    leave()
  })
}
