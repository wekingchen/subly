import { defineStore } from 'pinia'
import api, { logoutRefreshCookie, refreshTokens } from '../api'
import {
  bootstrapSession,
  clearAccessToken,
  clearBrowserSession,
  getAccessToken,
  removeLegacyTokens,
  setAccessToken
} from '../auth/session'

let initializePromise = null
const THEME_KEY = 'subly_theme'
const THEMES = new Set(['light', 'dark', 'ocean', 'forest', 'purple'])
const THEME_COLORS = { light: '#f6f8fc', dark: '#07111f', ocean: '#ecfeff', forest: '#f0fdf4', purple: '#faf5ff' }

function applyTheme(value) {
  const theme = THEMES.has(value) ? value : 'light'
  document.documentElement.dataset.theme = theme
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLORS[theme])
  try { localStorage.setItem(THEME_KEY, theme) } catch { /* 存储不可用时只更新当前页面。 */ }
  return theme
}

export const useAuth = defineStore('auth', {
  state: () => ({ user: null, initialized: false, _orderRevision: 0 }),
  getters: {
    isLoggedIn: (state) => Boolean(state.user && getAccessToken())
  },
  actions: {
    async initialize() {
      if (this.initialized) return this.isLoggedIn
      if (initializePromise) return initializePromise

      initializePromise = (async () => {
        clearAccessToken()
        try {
          const tokens = await bootstrapSession(refreshTokens)
          if (!tokens) {
            this.user = null
            this.initialized = true
            return false
          }
          await this.fetchMe()
          this.initialized = true
          return true
        } catch (error) {
          clearAccessToken()
          this.user = null
          throw error
        }
      })()

      try {
        return await initializePromise
      } finally {
        initializePromise = null
      }
    },
    async login(username, password) {
      const form = new URLSearchParams()
      form.append('username', username)
      form.append('password', password)
      const { data } = await api.post('/api/auth/login', form)
      setAccessToken(data.access_token)
      removeLegacyTokens()
      try {
        await this.fetchMe()
      } catch (error) {
        clearAccessToken()
        throw error
      }
      this.initialized = true
    },
    async register(username, email, password) {
      // 返回 { status: 'ok' | 'verify' | 'pending', message }，由页面决定后续流程
      const { data } = await api.post('/api/auth/register', { username, email, password })
      return data || { status: 'ok' }
    },
    async verifyEmail(email, code) {
      const { data } = await api.post('/api/auth/verify-email', { email, code })
      return data || { status: 'ok' }
    },
    async fetchMe() {
      const { data } = await api.get('/api/auth/me')
      data.theme = applyTheme(data.theme)
      // fetchMe 也改写 subscription_order（九审 Low 4：备份导入后服务器偏好
      // 已变）——应用的服务器快照与本地不同时前移修订号，让在途 updateMe
      // 的乱序保护识别「请求期间偏好已变」，不再用旧响应覆盖新快照
      const orderBefore = JSON.stringify(this.user?.subscription_order ?? null)
      this.user = data
      if (JSON.stringify(data.subscription_order ?? null) !== orderBefore) {
        this._orderRevision = (this._orderRevision || 0) + 1
      }
      return data
    },
    async updateMe(patch) {
      // 乱序保护（三审 Medium）：/api/me 响应是请求时刻的整对象快照。若响应
      // 期间 reorder 已本地合并新顺序（修订号前移），直接 this.user = data
      // 会把旧偏好覆盖回去——响应到达后再读当前 store 里的最新顺序（不是
      // 请求前快照，三审指出的错误时机），覆写响应值。首次修订号 0 → 1
      // 同样触发保护（不设 >0 门槛）。
      const startRevision = this._orderRevision || 0
      const { data } = await api.patch('/api/me', patch)
      const orderChangedDuringRequest = (this._orderRevision || 0) !== startRevision
      const latestOrder = orderChangedDuringRequest ? (this.user?.subscription_order ?? null) : null
      data.theme = applyTheme(data.theme)
      this.user = data
      if (orderChangedDuringRequest) {
        this.user.subscription_order = latestOrder
      }
      return data
    },
    // reorder 成功后由订阅页调用：本地合并手动顺序并前移修订号。
    // 偏好唯一持久化写入口是 reorder 事务本身，这里只同步 Pinia 缓存——
    // 不经 /api/me 整对象写回（复审 Medium 2：无锁整替会覆盖并发合并结果）
    rememberManualOrder(catKey, orderedIds) {
      if (!this.user) return
      const merged = { ...(this.user.subscription_order || {}), [String(catKey)]: [...orderedIds] }
      this.user.subscription_order = merged
      this._orderRevision = (this._orderRevision || 0) + 1
    },
    // 服务端已完成偏好清理（删除订阅/迁移分类/删除分类）后由调用方同步本地
    // 缓存（四审 Low）：残留的失效 ID 在 SQLite 复用主键时会让当前会话把新
    // 订阅恢复到被删记录的旧位置。参数可组合：
    // - purgeSubIds: 从所有 key 的列表中移除这些订阅 ID（删除/迁移）
    // - purgeCatKeys: 移除这些分类 key（删除分类）
    // 清空后的 key 一并移除；有任何变化前移修订号（让 updateMe 乱序保护生效）。
    purgeFromSubscriptionOrder({ purgeSubIds = [], purgeCatKeys = [] } = {}) {
      if (!this.user) return
      const saved = this.user.subscription_order
      if (!saved || typeof saved !== 'object') return
      const subSet = new Set(purgeSubIds)
      const keySet = new Set(purgeCatKeys.map(String))
      const next = {}
      let changed = false
      for (const [key, rawIds] of Object.entries(saved)) {
        if (keySet.has(key)) { changed = true; continue }
        let ids = rawIds
        if (Array.isArray(ids) && subSet.size && ids.some((id) => subSet.has(id))) {
          ids = ids.filter((id) => !subSet.has(id))
          changed = true
        }
        if (Array.isArray(ids) && ids.length) next[key] = ids
        else if (Array.isArray(ids)) changed = true // 清空的 key 移除
        else next[key] = ids // 非数组脏值原样保留
      }
      if (!changed) return
      this.user.subscription_order = Object.keys(next).length ? next : null
      this._orderRevision = (this._orderRevision || 0) + 1
    },
    async logout() {
      // HttpOnly Cookie 只能由服务端删除；请求失败时保留当前会话并让界面明确提示重试。
      await logoutRefreshCookie()
      clearBrowserSession()
      this.user = null
      this.initialized = true
    }
  }
})
