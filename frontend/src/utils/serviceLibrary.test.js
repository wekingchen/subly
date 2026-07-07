import { describe, expect, it } from 'vitest'

import {
  buildServicePickPatch,
  findCategoryIdByServiceKey,
  getServiceCategoryKeys,
  getServiceCategoryLabel,
  groupServicesByCategory,
  isCarrierCategory,
  isVpsCategory,
  suggestServicesByName
} from './serviceLibrary'

const categories = [
  { id: 1, name: 'Streaming' },
  { id: 2, name: 'AI Tools' },
  { id: 3, name: 'My VPS' },
  { id: 4, name: '流媒体' }
]

describe('getServiceCategoryKeys', () => {
  it('cleans category_keys and preserves order', () => {
    expect(getServiceCategoryKeys({ category_keys: [' streaming ', '', 'music'] })).toEqual(['streaming', 'music'])
  })

  it('falls back to legacy category or other', () => {
    expect(getServiceCategoryKeys({ category: 'ai' })).toEqual(['ai'])
    expect(getServiceCategoryKeys({})).toEqual(['other'])
  })
})

describe('getServiceCategoryLabel', () => {
  it('prefers category_labels by index', () => {
    expect(getServiceCategoryLabel({ category_labels: ['流媒体', '音乐'] }, 'music', 1)).toBe('音乐')
  })

  it('falls back to legacy label or key', () => {
    expect(getServiceCategoryLabel({ category: 'ai', category_label: 'AI' }, 'ai', 0)).toBe('AI')
    expect(getServiceCategoryLabel({}, 'other', 0)).toBe('other')
  })
})

describe('findCategoryIdByServiceKey', () => {
  it('matches category names by the existing English keyword mapping', () => {
    expect(findCategoryIdByServiceKey('ai', categories)).toBe(2)
    expect(findCategoryIdByServiceKey('vps', categories)).toBe(3)
  })

  it('returns null for unknown keys or unmatched localized names', () => {
    expect(findCategoryIdByServiceKey('unknown', categories)).toBeNull()
    expect(findCategoryIdByServiceKey('streaming', [{ id: 1, name: '流媒体' }])).toBeNull()
  })

  it('returns the first matching category', () => {
    expect(findCategoryIdByServiceKey('ai', [
      { id: 8, name: 'AI' },
      { id: 9, name: 'AI Backup' }
    ])).toBe(8)
  })
})

describe('isVpsCategory', () => {
  it('detects vps and server category names', () => {
    expect(isVpsCategory({ name: 'VPS' })).toBe(true)
    expect(isVpsCategory({ name: '云服务器' })).toBe(true)
  })

  it('returns false for ordinary or missing categories', () => {
    expect(isVpsCategory({ name: 'AI' })).toBe(false)
    expect(isVpsCategory(null)).toBe(false)
  })
})

describe('isCarrierCategory', () => {
  it('detects carrier category names', () => {
    expect(isCarrierCategory({ name: '电信运营商 / Carrier (SIM 保号)' })).toBe(true)
    expect(isCarrierCategory({ name: '手机运营商' })).toBe(true)
  })

  it('returns false for ordinary or missing categories', () => {
    expect(isCarrierCategory({ name: 'AI' })).toBe(false)
    expect(isCarrierCategory(null)).toBe(false)
  })
})

describe('suggestServicesByName', () => {
  const services = Array.from({ length: 8 }, (_, i) => ({ name: `Claude ${i + 1}` }))

  it('matches names case-insensitively and limits results', () => {
    expect(suggestServicesByName(services, ' claude ')).toHaveLength(6)
  })

  it('returns an empty list for empty queries', () => {
    expect(suggestServicesByName(services, '   ')).toEqual([])
  })
})

describe('buildServicePickPatch', () => {
  it('fills service identity, website and matched category', () => {
    expect(buildServicePickPatch({ url: '', category_id: 1 }, {
      name: 'Claude',
      icon: '🤖',
      website: 'https://claude.ai',
      category_keys: ['ai']
    }, categories)).toEqual({
      name: 'Claude',
      icon: '🤖',
      url: 'https://claude.ai',
      category_id: 2
    })
  })

  it('does not override an existing url or unmatched category', () => {
    expect(buildServicePickPatch({ url: 'https://custom.example', category_id: 1 }, {
      name: 'Unknown',
      icon: '❔',
      website: 'https://example.com',
      category_keys: ['unknown']
    }, categories)).toEqual({
      name: 'Unknown',
      icon: '❔'
    })
  })

  it('uses the first matching category key', () => {
    expect(buildServicePickPatch({ url: '' }, {
      name: 'Bundle',
      icon: '📦',
      category_keys: ['unknown', 'vps', 'ai']
    }, categories).category_id).toBe(3)
  })
})

describe('groupServicesByCategory', () => {
  const services = [
    { slug: 'a', name: 'Alpha', category_keys: ['streaming', 'ai'], category_labels: ['流媒体', 'AI'] },
    { slug: 'b', name: 'Beta', category: 'ai', category_label: 'AI' },
    { slug: 'c', name: 'Gamma', category: 'vps', category_label: 'VPS' }
  ]

  it('groups services by every category key while preserving order', () => {
    expect(groupServicesByCategory(services, '')).toEqual([
      { key: 'streaming', label: '流媒体', items: [services[0]] },
      { key: 'ai', label: 'AI', items: [services[0], services[1]] },
      { key: 'vps', label: 'VPS', items: [services[2]] }
    ])
  })

  it('filters groups by service name query', () => {
    expect(groupServicesByCategory(services, 'beta')).toEqual([
      { key: 'ai', label: 'AI', items: [services[1]] }
    ])
  })
})
