import { computed, ref } from 'vue'
import api from '../api'
import { useDataRequest } from '../utils/dataRequest'

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
      const payload = buildCreditCardPayload(source)
      const response = card?.id
        ? await api.put(`/api/credit-cards/${card.id}`, payload)
        : await api.post('/api/credit-cards', payload)
      const saved = response.data
      if (saved?.id) {
        const index = cards.value.findIndex((item) => item.id === saved.id)
        if (index >= 0) cards.value.splice(index, 1, saved)
        else cards.value.unshift(saved)
      } else {
        await load()
      }
      return saved || null
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
