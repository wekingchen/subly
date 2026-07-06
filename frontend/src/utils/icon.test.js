import { describe, expect, it } from 'vitest'

import { emojiOf, isImg } from './icon'

describe('isImg', () => {
  it('treats absolute paths and http(s) URLs as images', () => {
    expect(isImg('/static/icons/netflix.png')).toBe(true)
    expect(isImg('/foo/bar.svg')).toBe(true)
    expect(isImg('https://example.com/a.png')).toBe(true)
    expect(isImg('http://example.com/a.png')).toBe(true)
  })

  it('treats emoji and bare text as non-images (so they can render as fallback text)', () => {
    expect(isImg('🎬')).toBe(false)
    expect(isImg('netflix')).toBe(false)
    expect(isImg('data:image/png;base64,...')).toBe(false)
  })

  it('rejects non-strings and empties', () => {
    expect(isImg(null)).toBe(false)
    expect(isImg(undefined)).toBe(false)
    expect(isImg(123)).toBe(false)
    expect(isImg('')).toBe(false)
  })
})

describe('emojiOf', () => {
  it('returns the icon when it is an emoji / bare text, not an image path', () => {
    expect(emojiOf({ icon: '🎬' })).toBe('🎬')
    expect(emojiOf({ icon: 'netflix' })).toBe('netflix')
  })

  it('falls back to the bookmark symbol for image icons — image URLs cannot render as fallback text', () => {
    expect(emojiOf({ icon: '/static/icons/a.png' })).toBe('🔖')
    expect(emojiOf({ icon: 'https://example.com/a.png' })).toBe('🔖')
  })

  it('falls back when there is no icon at all', () => {
    expect(emojiOf({})).toBe('🔖')
    expect(emojiOf(null)).toBe('🔖')
    expect(emojiOf(undefined)).toBe('🔖')
  })
})
