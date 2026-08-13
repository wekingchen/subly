import { onBeforeUnmount, ref } from 'vue'

export function useToasts({ duration = 2600 } = {}) {
  const toasts = ref([])
  const timers = new Map()
  let nextId = 0

  function add(message, type = 'ok') {
    const id = ++nextId
    toasts.value.push({ id, message, type })
    timers.set(id, setTimeout(() => remove(id), duration))
    return id
  }

  function remove(id) {
    const timer = timers.get(id)
    if (timer) clearTimeout(timer)
    timers.delete(id)
    toasts.value = toasts.value.filter((toast) => toast.id !== id)
  }

  onBeforeUnmount(() => {
    timers.forEach((timer) => clearTimeout(timer))
    timers.clear()
  })

  return { toasts, add, remove }
}
