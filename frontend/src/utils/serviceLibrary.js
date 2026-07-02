export const SERVICE_CATEGORY_KEYWORDS = {
  streaming: 'streaming', music: 'music', ai: 'ai', gaming: 'gaming', vps: 'vps',
  carrier: 'carrier', cloud: 'cloud', software: 'software', domain: 'domain',
  education: 'education', news: 'news', fitness: 'fitness', membership: 'membership', other: 'other'
}

export function getServiceCategoryKeys(service) {
  const keys = Array.isArray(service?.category_keys) ? service.category_keys : []
  const clean = keys.map((x) => String(x || '').trim()).filter(Boolean)
  return clean.length ? clean : [service?.category || 'other']
}

export function getServiceCategoryLabel(service, key, index) {
  const labels = Array.isArray(service?.category_labels) ? service.category_labels : []
  return labels[index] || (service?.category === key ? service.category_label : '') || key
}

export function findCategoryIdByServiceKey(key, categories) {
  const kw = SERVICE_CATEGORY_KEYWORDS[key]
  if (!kw) return null
  const hit = categories.find((c) => (c.name || '').toLowerCase().includes(kw))
  return hit ? hit.id : null
}

export function isVpsCategory(category) {
  if (!category) return false
  const name = category.name || ''
  return name.toLowerCase().includes('vps') || name.includes('服务器')
}

export function suggestServicesByName(services, query, limit = 6) {
  const q = (query || '').toLowerCase().trim()
  if (q.length < 1) return []
  return services.filter((s) => (s.name || '').toLowerCase().includes(q)).slice(0, limit)
}

export function buildServicePickPatch(currentForm, service, categories) {
  const patch = { name: service.name, icon: service.icon }
  if (!currentForm?.url && service.website) patch.url = service.website
  for (const key of getServiceCategoryKeys(service)) {
    const categoryId = findCategoryIdByServiceKey(key, categories)
    if (categoryId) {
      patch.category_id = categoryId
      break
    }
  }
  return patch
}

export function groupServicesByCategory(services, query = '') {
  const q = query.toLowerCase().trim()
  const groups = new Map()
  for (const service of services) {
    if (q && !(service.name || '').toLowerCase().includes(q)) continue
    getServiceCategoryKeys(service).forEach((key, index) => {
      if (!groups.has(key)) groups.set(key, { key, label: getServiceCategoryLabel(service, key, index), items: [] })
      groups.get(key).items.push(service)
    })
  }
  return [...groups.values()]
}
