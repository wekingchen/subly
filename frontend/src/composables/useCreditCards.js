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
  // 待还款汇总：所有已出账单未标记还款的合计（mismatch 不计入，见后端契约）。
  // 标记/取消还款后 refreshOutstanding() 实时刷新。
  // outstandingError：汇总失败必须响亮——把未知状态伪装成「0 待还」会掩盖真实欠款。
  const outstanding = ref({ total: 0, unrepaid_count: 0, per_card: [] })
  const outstandingError = ref(false)
  let outstandingSeq = 0

  async function load() {
    return request.run(async () => (await api.get('/api/credit-cards')).data || [])
  }

  async function refreshOutstanding() {
    // 请求序号防竞态：连续两次标记切换时，慢的旧响应不能覆盖新状态
    const seq = ++outstandingSeq
    try {
      const data = (await api.get('/api/credit-cards/outstanding/summary')).data
      if (seq !== outstandingSeq) return
      outstanding.value = data
      outstandingError.value = false
    } catch (error) {
      if (seq !== outstandingSeq) return // 已有更新的请求接管状态
      // 首次加载失败没有可用数据，置错误态（页面显示明确失败而非 0）；
      // 标记后的刷新失败保留旧值但同样置错，调用方 toast 提示重试
      outstandingError.value = true
      throw error
    }
  }

  // 卡片上「标记已还款」：一次标记该卡全部未标记账单（含历史各期）。
  // 界线推进改变了派生字段（next_due_date 等）：用响应里的更新卡片
  // 原位替换本地状态，再刷新待还汇总（「实时刷新」要求）。
  async function markCardRepaid(card) {
    if (mutationPending.value || !card?.id) return false
    mutationPending.value = true
    try {
      const { data } = await api.post(`/api/credit-cards/${card.id}/mark-repaid`)
      if (data?.card) {
        const index = cards.value.findIndex((item) => item.id === data.card.id)
        if (index >= 0) cards.value.splice(index, 1, data.card)
      }
      await refreshOutstanding()
      return true
    } finally {
      mutationPending.value = false
    }
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
    outstanding,
    outstandingError,
    load,
    refreshOutstanding,
    markCardRepaid,
    save,
    remove
  }
}
