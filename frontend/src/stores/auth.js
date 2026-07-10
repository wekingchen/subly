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
      this.user = data
      document.documentElement.setAttribute('data-theme', data.theme || 'light')
      return data
    },
    async updateMe(patch) {
      const { data } = await api.patch('/api/me', patch)
      this.user = data
      if (patch.theme) document.documentElement.setAttribute('data-theme', patch.theme)
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
