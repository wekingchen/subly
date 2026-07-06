// 图标资源判定：区分「图片 URL/路径」与「emoji 文本」，用于决定 fallback 显示
export function isImg(v) { return typeof v === 'string' && (v.startsWith('/') || v.startsWith('http')) }

// 取订阅的 emoji 图标；只有非图片的 icon 才当作 emoji，否则回退到默认书签符号
export function emojiOf(s) { return s && s.icon && !isImg(s.icon) ? s.icon : '🔖' }
