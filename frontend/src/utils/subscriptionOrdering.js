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
    // 默认按剩余订阅时间由近及远：到期日越早越靠前（用户确认口径）；
    // 无到期日的（一次性买断已结束/缺日期）沉底，组内保持原相对顺序
    byCat[key].sort((a, b) => {
      const da = a.next_renewal_date || ''
      const db = b.next_renewal_date || ''
      if (!da && !db) return (a.sort - b.sort) || (a.id - b.id)
      if (!da) return 1
      if (!db) return -1
      return da < db ? -1 : da > db ? 1 : (a.sort - b.sort) || (a.id - b.id)
    })
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

// 用户已手动拖拽排序的分类 key 集合（持久化于用户偏好 subscription_order）。
// 这些分类的展示顺序直接采用 orderMap 中已持久化的 ID 顺序（即订阅上的
// sort 字段序），不再被「按剩余订阅时间」的默认排序覆盖（审核 Medium：
// 分类成员新增/删除/迁移会改变 sort 序列形态，无法从 sort 值推断手动状态，
// 必须显式持久化）。
export function getManuallyOrderedKeys(savedSubscriptionOrder) {
  return new Set(Object.keys(savedSubscriptionOrder || {}))
}

// 规范化持久化的手动排序偏好（复审 Low）：过滤已失效的订阅 ID、追加新成员
// 到末尾、跳过已空/已迁出的分类（不写 key——空数组会让该分类永久进入
// 「持久化顺序」路径，之后新订阅按加入顺序排列而非默认日期排序）。
// 纯函数：不修改入参。返回 { normalized, orderChanged, applied }：
// - normalized: 规范化后的偏好对象（orderChanged 时整体写回用户偏好）
// - orderChanged: 与传入偏好是否有差异（成员一进一出时长度相同但内容已变，
//   必须内容比较而非只比长度）
// - applied: key → 规范化后的有序 ID 列表（调用方写回 orderMap 恢复拖拽顺序）
export function normalizeSavedSubscriptionOrder(savedSubOrder, orderMap) {
  const normalized = {}
  const applied = {}
  let orderChanged = false
  for (const [key, ids] of Object.entries(savedSubOrder || {})) {
    if (!Array.isArray(ids)) continue // 历史脏数据防御
    const current = orderMap[key] || []
    if (!current.length) {
      orderChanged = true // 已是空数组 key 也规范化省略（复审 Low）
      continue
    }
    const cleaned = ids.filter((id) => current.includes(id))
    for (const id of current) if (!cleaned.includes(id)) cleaned.push(id)
    normalized[key] = cleaned
    applied[key] = cleaned
    if (JSON.stringify(cleaned) !== JSON.stringify(ids)) orderChanged = true
  }
  return { normalized, orderChanged, applied }
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
