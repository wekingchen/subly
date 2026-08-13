const CATEGORY_PALETTE = [
  '#5b5bd6', '#0891b2', '#15803d', '#b45309', '#dc2626', '#9333ea',
  '#0369a1', '#be185d', '#0f766e', '#c2410c', '#6d28d9', '#4d7c0f'
]

export const UNCATEGORIZED_COLOR = '#64748b'

function hashKey(value) {
  const text = String(value ?? '')
  let hash = 0
  for (let index = 0; index < text.length; index += 1) {
    hash = ((hash << 5) - hash + text.charCodeAt(index)) | 0
  }
  return Math.abs(hash)
}

export function categoryVisualKey(category) {
  return category?.category_id == null ? 'uncategorized' : String(category.category_id)
}

export function categoryColor(category) {
  const saved = typeof category?.category_color === 'string' ? category.category_color.trim() : ''
  if (saved) return saved
  if (category?.category_id == null) return UNCATEGORIZED_COLOR
  return CATEGORY_PALETTE[hashKey(category.category_id) % CATEGORY_PALETTE.length]
}
