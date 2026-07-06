export function amountOf(item, fallback = 0) {
  const raw = item ? item.amount_in_base ?? item.amount ?? fallback : fallback
  const value = Number(raw)
  const safeFallback = Number(fallback)
  if (Number.isFinite(value)) return value
  return Number.isFinite(safeFallback) ? safeFallback : 0
}

// 拆分金额为「币种段」与「金额段」，供需要差异化字号时使用。
// currencyPart 为纯币种（不含空格），空格由调用方按 space 选项拼接；无币种或 position=none 时为空。
// formatMoney 内部复用本函数做归一化，保证两条路径不漂移。
export function splitMoney(value, currency = 'CNY', options = {}) {
  const position = options.position || 'prefix'
  const amount = Number(value)
  const amountPart = (Number.isFinite(amount) ? amount : 0).toFixed(options.decimals ?? 2)
  if (!currency || position === 'none') return { currencyPart: '', amountPart }
  return { currencyPart: currency, amountPart }
}

export function formatMoney(value, currency = 'CNY', options = {}) {
  const position = options.position || 'prefix'
  const hasSpace = options.space !== false
  const { currencyPart, amountPart } = splitMoney(value, currency, { ...options, position })
  if (!currencyPart) return amountPart
  const sep = hasSpace ? ' ' : ''
  return position === 'suffix' ? `${amountPart}${sep}${currencyPart}` : `${currencyPart}${sep}${amountPart}`
}


export function hasBaseEquivalent(item, baseCurrency) {
  if (!item || typeof item.currency === 'boolean' || typeof baseCurrency === 'boolean') return false
  const itemCurrency = String(item.currency || '').trim().toUpperCase()
  const base = String(baseCurrency || '').trim().toUpperCase()
  if (!itemCurrency || !base || itemCurrency === base) return false
  const raw = item.amount_in_base
  if (raw == null || typeof raw === 'boolean') return false
  if (typeof raw === 'string' && raw.trim() === '') return false
  return Number.isFinite(Number(raw))
}
