import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// updateMe 乱序响应保护（三审 Medium）与 rememberManualOrder 的 store 测试：
// mock ../api 验证真实修订号逻辑——乱序 /api/me 响应不得覆盖请求期间
// reorder 已本地合并的顺序（含修订号 0→1 的首次拖拽场景）。
vi.mock('../api', () => ({
  default: { patch: vi.fn(), get: vi.fn(), post: vi.fn() },
  logoutRefreshCookie: vi.fn(),
  refreshTokens: vi.fn()
}))
vi.mock('../auth/session', () => ({
  bootstrapSession: vi.fn(),
  clearAccessToken: vi.fn(),
  clearBrowserSession: vi.fn(),
  getAccessToken: () => 'token',
  removeLegacyTokens: vi.fn(),
  setAccessToken: vi.fn()
}))

import api from '../api'
import { useAuth } from './auth'

// vitest environment 是 node（无 DOM）：stub applyTheme 用到的 document，
// 行为与 jsdom 下的 dataset/meta 一致即可
vi.stubGlobal('document', {
  documentElement: { dataset: {} },
  querySelector: () => null
})

function deferred() {
  let resolve
  const promise = new Promise((r) => { resolve = r })
  return { promise, resolve }
}

describe('auth store：手动排序偏好与 updateMe 乱序保护', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.patch).mockReset()
  })

  it('rememberManualOrder 本地合并偏好并前移修订号', () => {
    const auth = useAuth()
    auth.user = { subscription_order: { '1': [7] } }
    auth.rememberManualOrder('2', [9, 8])
    expect(auth.user.subscription_order).toEqual({ '1': [7], '2': [9, 8] })
    expect(auth._orderRevision).toBe(1)
  })

  it('乱序响应（期间修订号 0→1）：响应到达后保留最新合并顺序而非请求前快照', async () => {
    const auth = useAuth()
    auth.user = { theme: 'light', subscription_order: null }
    const pending = deferred()
    vi.mocked(api.patch).mockReturnValue(pending.promise)

    const updatePromise = auth.updateMe({ theme: 'dark' }) // 请求前修订号 0
    // 响应未到时用户拖拽：顺序 A → B，修订号 0 → 1
    auth.rememberManualOrder('1', [3, 2, 1])
    pending.resolve({ data: { theme: 'dark', subscription_order: null } }) // 服务器快照：无偏好
    await updatePromise

    // 不得被响应里的旧快照（null）覆盖回 A 之前的空值
    expect(auth.user.subscription_order).toEqual({ '1': [3, 2, 1] })
    expect(auth._orderRevision).toBe(1)
  })

  it('乱序响应（修订号非零继续前移）：用 store 当前最新顺序覆写响应', async () => {
    const auth = useAuth()
    auth.user = { theme: 'light', subscription_order: { '1': [7] } }
    auth._orderRevision = 2
    const pending = deferred()
    vi.mocked(api.patch).mockReturnValue(pending.promise)

    const updatePromise = auth.updateMe({ base_currency: 'USD' })
    auth.rememberManualOrder('1', [7, 5, 6]) // 修订号 2 → 3
    pending.resolve({ data: { theme: 'light', subscription_order: { '1': [7] } } }) // 旧快照 A
    await updatePromise

    expect(auth.user.subscription_order).toEqual({ '1': [7, 5, 6] })
  })

  it('无并发拖拽时响应正常落地（保护不触发）', async () => {
    const auth = useAuth()
    auth.user = { theme: 'light', subscription_order: null }
    vi.mocked(api.patch).mockResolvedValue({ data: { theme: 'ocean', subscription_order: null } })

    await auth.updateMe({ theme: 'ocean' })
    expect(auth.user.theme).toBe('ocean')
    expect(auth._orderRevision).toBe(0)
  })
})

describe('purgeFromSubscriptionOrder（四审 Low：服务端清理后同步本地缓存）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.patch).mockReset()
  })

  it('按订阅 ID 清除：从所有 key 列表移除该 ID，清空的 key 移除，修订号前移', () => {
    const auth = useAuth()
    auth.user = { subscription_order: { '1': [7, 8], none: [7] } }
    auth.purgeFromSubscriptionOrder({ purgeSubIds: [7] })
    expect(auth.user.subscription_order).toEqual({ '1': [8] })
    expect(auth._orderRevision).toBe(1)
  })

  it('按分类 key 清除：整个 key 移除，其他 key 保留', () => {
    const auth = useAuth()
    auth.user = { subscription_order: { '12': [31, 30], '5': [2] } }
    auth.purgeFromSubscriptionOrder({ purgeCatKeys: ['12'] })
    expect(auth.user.subscription_order).toEqual({ '5': [2] })
    expect(auth._orderRevision).toBe(1)
  })

  it('全清空时偏好置 null；无变化时不动修订号', () => {
    const auth = useAuth()
    auth.user = { subscription_order: { '1': [7] } }
    auth.purgeFromSubscriptionOrder({ purgeSubIds: [7] })
    expect(auth.user.subscription_order).toBeNull()
    expect(auth._orderRevision).toBe(1)

    const revisionBefore = auth._orderRevision
    auth.purgeFromSubscriptionOrder({ purgeSubIds: [999] })  // 不存在的 ID
    auth.purgeFromSubscriptionOrder({ purgeCatKeys: ['404'] }) // 不存在的 key
    expect(auth._orderRevision).toBe(revisionBefore)
  })

  it('ID 复用场景：删除最大 ID 后偏好不再含该 ID，新订阅不继承旧位置', () => {
    const auth = useAuth()
    // 手动顺序 [2, 1]；删除 id=2（服务端已清，本地同步）
    auth.user = { subscription_order: { '1': [2, 1] } }
    auth.purgeFromSubscriptionOrder({ purgeSubIds: [2] })
    expect(auth.user.subscription_order).toEqual({ '1': [1] })
    // 之后新建订阅复用 id=2：rebuild 的 normalize 只认本地偏好 [1]，
    // 新 id=2 作为新成员追加到末尾，不继承旧位置
  })

  it('无偏好或无 user 时安全跳过', () => {
    const auth = useAuth()
    auth.user = null
    expect(() => auth.purgeFromSubscriptionOrder({ purgeSubIds: [1] })).not.toThrow()
    auth.user = { subscription_order: null }
    auth.purgeFromSubscriptionOrder({ purgeSubIds: [1] })
    expect(auth._orderRevision).toBe(0)
  })
})

describe('fetchMe 修订号（九审 Low 4）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.patch).mockReset()
    vi.mocked(api.get).mockReset()
  })

  it('fetchMe 应用不同偏好时前移修订号——在途 updateMe 保留新快照顺序', async () => {
    const auth = useAuth()
    auth.user = { theme: 'light', subscription_order: { '1': [7] } }
    auth._orderRevision = 0

    // 在途 updateMe（响应慢，携带旧顺序 A）
    const pending = deferred()
    vi.mocked(api.patch).mockReturnValue(pending.promise)
    const updatePromise = auth.updateMe({ theme: 'dark' })

    // 期间备份导入完成，fetchMe 拉到新快照 B
    vi.mocked(api.get).mockResolvedValue({ data: { theme: 'light', subscription_order: { '1': [9, 8] } } })
    await auth.fetchMe()
    expect(auth.user.subscription_order).toEqual({ '1': [9, 8] })
    expect(auth._orderRevision).toBe(1)  // fetchMe 前移了修订号

    // 迟到的 updateMe 响应（旧顺序 A）——保护触发，保留 B
    pending.resolve({ data: { theme: 'dark', subscription_order: { '1': [7] } } })
    await updatePromise
    expect(auth.user.subscription_order).toEqual({ '1': [9, 8] })
  })

  it('fetchMe 偏好未变时不前移修订号', async () => {
    const auth = useAuth()
    auth.user = { theme: 'light', subscription_order: { '1': [7] } }
    vi.mocked(api.get).mockResolvedValue({ data: { theme: 'ocean', subscription_order: { '1': [7] } } })
    await auth.fetchMe()
    expect(auth._orderRevision).toBe(0)
  })
})
