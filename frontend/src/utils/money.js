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
