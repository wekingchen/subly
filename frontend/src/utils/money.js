export function amountOf(item, fallback = 0) {
  const raw = item ? item.amount_in_base ?? item.amount ?? fallback : fallback
  const value = Number(raw)
  const safeFallback = Number(fallback)
  if (Number.isFinite(value)) return value
  return Number.isFinite(safeFallback) ? safeFallback : 0
}

export function formatMoney(value, currency = 'CNY', options = {}) {
  const decimals = options.decimals ?? 2
  const position = options.position || 'prefix'
  const hasSpace = options.space !== false
  const amount = Number(value)
  const fixed = (Number.isFinite(amount) ? amount : 0).toFixed(decimals)
  if (!currency || position === 'none') return fixed
  if (position === 'suffix') return `${fixed}${hasSpace ? ' ' : ''}${currency}`
  return `${currency}${hasSpace ? ' ' : ''}${fixed}`
}

// 拆分金额为「币种段」与「金额段」，供需要差异化字号时使用。
// 与 formatMoney 严格等价：currencyText + amountText 按规则拼接 === formatMoney 输出。
// 无币种或 position=none 时 currencyText 为空。
export function splitMoney(value, currency = 'CNY', options = {}) {
  const position = options.position || 'prefix'
  const amount = Number(value)
  const amountPart = (Number.isFinite(amount) ? amount : 0).toFixed(options.decimals ?? 2)
  if (!currency || position === 'none') return { currencyPart: '', amountPart }
  return { currencyPart: currency, amountPart }
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
