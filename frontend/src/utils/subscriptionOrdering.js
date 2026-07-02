export const UNCATEGORIZED_KEY = 'none'

export function getSubscriptionCategoryKey(subscription) {
  return subscription?.category_id == null ? UNCATEGORIZED_KEY : String(subscription.category_id)
}

export function getCategoryMeta(key, categories, options = {}) {
  if (key === UNCATEGORIZED_KEY) return { icon: '🗂️', name: options.uncategorizedName || '' }
  const category = categories.find((x) => String(x.id) === key)
  return category ? { icon: category.icon || '📁', name: category.name } : { icon: '📁', name: key }
}

export function buildSubscriptionOrderState(subscriptions, categories, savedCategoryOrder = []) {
  const orderMap = {}
  const byCat = {}
  for (const subscription of subscriptions) {
    const key = getSubscriptionCategoryKey(subscription)
    ;(byCat[key] ||= []).push(subscription)
  }
  for (const key of Object.keys(byCat)) {
    byCat[key].sort((a, b) => (a.sort - b.sort) || (a.id - b.id))
    orderMap[key] = byCat[key].map((subscription) => subscription.id)
  }

  const present = new Set(Object.keys(orderMap))
  const saved = (savedCategoryOrder || []).map(String)
  const catOrder = []
  for (const key of saved) {
    if (present.has(key)) {
      catOrder.push(key)
      present.delete(key)
    }
  }
  const rest = [...present].filter((key) => key !== UNCATEGORIZED_KEY)
    .sort((a, b) => {
      const ca = categories.find((x) => String(x.id) === a)
      const cb = categories.find((x) => String(x.id) === b)
      return ((ca?.sort ?? 999) - (cb?.sort ?? 999)) || (Number(a) - Number(b))
    })
  catOrder.push(...rest)
  if (present.has(UNCATEGORIZED_KEY)) catOrder.push(UNCATEGORIZED_KEY)
  return { orderMap, catOrder }
}

export function buildGroupedSubscriptions(subscriptions, orderMap, catOrder, categories, options = {}) {
  return catOrder
    .filter((key) => orderMap[key] && orderMap[key].length)
    .map((key) => {
      const meta = getCategoryMeta(key, categories, options)
      const items = orderMap[key].map((id) => subscriptions.find((subscription) => subscription.id === id)).filter(Boolean)
      return { key, icon: meta.icon, name: meta.name, items }
    })
}

export function moveValueByOffset(list, value, offset) {
  const from = list.indexOf(value)
  const to = from + offset
  if (from < 0 || to < 0 || to >= list.length) return list
  const next = [...list]
  next.splice(to, 0, next.splice(from, 1)[0])
  return next
}

export function moveValueToTarget(list, movingValue, targetValue) {
  const from = list.indexOf(movingValue)
  const to = list.indexOf(targetValue)
  if (from < 0 || to < 0 || movingValue === targetValue) return list
  const next = [...list]
  next.splice(to, 0, next.splice(from, 1)[0])
  return next
}

function appendUncategorizedIfPresent(realOrder, sourceOrder) {
  return sourceOrder.includes(UNCATEGORIZED_KEY) ? [...realOrder, UNCATEGORIZED_KEY] : realOrder
}

export function moveCategoryByOffset(catOrder, key, offset) {
  if (key === UNCATEGORIZED_KEY) return catOrder
  const realOrder = catOrder.filter((item) => item !== UNCATEGORIZED_KEY)
  const moved = moveValueByOffset(realOrder, key, offset)
  return moved === realOrder ? catOrder : appendUncategorizedIfPresent(moved, catOrder)
}

export function moveCategoryToTarget(catOrder, movingKey, targetKey) {
  if (movingKey === UNCATEGORIZED_KEY || targetKey === UNCATEGORIZED_KEY) return catOrder
  const realOrder = catOrder.filter((item) => item !== UNCATEGORIZED_KEY)
  const moved = moveValueToTarget(realOrder, movingKey, targetKey)
  return moved === realOrder ? catOrder : appendUncategorizedIfPresent(moved, catOrder)
}

export function categoryOrderToPersistedIds(catOrder) {
  return catOrder.filter((key) => key !== UNCATEGORIZED_KEY).map(Number)
}
