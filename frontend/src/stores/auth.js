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
  state: () => ({ user: null, initialized: false }),
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
      this.user = data
      return data
    },
    async updateMe(patch) {
      const { data } = await api.patch('/api/me', patch)
      data.theme = applyTheme(data.theme)
      this.user = data
      return data
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
