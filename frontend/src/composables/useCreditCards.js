import { computed, ref } from 'vue'
import api from '../api'
import { useDataRequest } from '../utils/dataRequest'

// 批量建卡时名称自动拼尾号区分；用户名称已含该尾号则不重复。
function displayNameFor(displayName, lastFour) {
  const base = String(displayName || '').trim()
  if (!lastFour) return base
  if (base.includes(lastFour)) return base
  return base ? `${base} ${lastFour}` : lastFour
}

export function buildCreditCardPayload(source) {
  const remindDays = Array.isArray(source?.remind_days_before)
    ? source.remind_days_before
    : String(source?.remind_days_before ?? '')
      .split(/[,，\s]+/)
      .filter(Boolean)
  return {
    display_name: String(source?.display_name || '').trim(),
    bank_name: String(source?.bank_name || '').trim(),
    last_four: String(source?.last_four || '').trim(),
    statement_day: Number(source?.statement_day),
    due_day: Number(source?.due_day),
    remind_days_before: remindDays.map(Number),
    credit_limit:
      source?.credit_limit === '' || source?.credit_limit === null || source?.credit_limit === undefined
        ? null
        : Number(source.credit_limit),
    is_active: source?.is_active !== false,
    show_in_calendar: source?.show_in_calendar !== false
  }
}

export function useCreditCards() {
  const request = useDataRequest({ initialData: [] })
  const mutationPending = ref(false)
  const cards = request.data
  const dataState = computed(() => request.state())
  const activeCards = computed(() => cards.value.filter((card) => card.is_active))

  async function load() {
    return request.run(async () => (await api.get('/api/credit-cards')).data || [])
  }

  async function save(card, source) {
    if (mutationPending.value) return null
    mutationPending.value = true
    try {
      // 编辑：单卡走 PUT，契约与既有行为一致。
      if (card?.id) {
        const payload = buildCreditCardPayload(source)
        const response = await api.put(`/api/credit-cards/${card.id}`, payload)
        const saved = response.data
        const index = cards.value.findIndex((item) => item.id === saved.id)
        if (index >= 0) cards.value.splice(index, 1, saved)
        else cards.value.unshift(saved)
        return { created: 1, total: 1, items: [saved], remainingLastFours: [] }
      }

      // 新建：尾号多值（如 1234,2234）时逐张创建，名称自动拼尾号区分。
      // 空尾号视为单卡（lastFour 为空串），与后端"尾号可选"契约一致。
      const lastFours = Array.isArray(source?.last_fours) && source.last_fours.length
        ? [...source.last_fours]
        : [String(source?.last_four || '').trim()]
      const items = []
      for (let index = 0; index < lastFours.length; index += 1) {
        const lastFour = lastFours[index]
        const payload = buildCreditCardPayload({
          ...source,
          display_name: displayNameFor(source.display_name, lastFour),
          last_four: lastFour
        })
        try {
          const response = await api.post('/api/credit-cards', payload)
          const saved = response.data
          if (saved?.id) cards.value.unshift(saved)
          items.push(saved)
        } catch (error) {
          // 部分成功要响亮：携带结构化批次结果，剩余尾号供 UI 回填重试，避免重复创建已成功项。
          error.batch = {
            created: items.length,
            total: lastFours.length,
            failedIndex: index,
            failedReason: error,
            remainingLastFours: lastFours.slice(index)
          }
          throw error
        }
      }
      return { created: items.length, total: lastFours.length, items, remainingLastFours: [] }
    } finally {
      mutationPending.value = false
    }
  }

  async function remove(card) {
    if (!card?.id || mutationPending.value) return false
    mutationPending.value = true
    try {
      await api.delete(`/api/credit-cards/${card.id}`)
      cards.value = cards.value.filter((item) => item.id !== card.id)
      return true
    } finally {
      mutationPending.value = false
    }
  }

  return {
    cards,
    activeCards,
    dataState,
    initialLoading: request.initialLoading,
    refreshing: request.refreshing,
    stale: request.stale,
    error: request.error,
    mutationPending,
    load,
    save,
    remove
  }
}
