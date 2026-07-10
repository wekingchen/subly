import axios from 'axios'
import {
  clearBrowserSession,
  getAccessToken,
  setAccessToken
} from '../auth/session'

const api = axios.create({ baseURL: '/', withCredentials: true })
const authApi = axios.create({ baseURL: '/', withCredentials: true })

const NO_AUTO_REFRESH = new Set([
  '/api/auth/login',
  '/api/auth/register',
  '/api/auth/verify-email',
  '/api/auth/refresh',
  '/api/auth/logout'
])
const ACCOUNT_BLOCK_DETAILS = new Set([
  '请先完成邮箱验证',
  '账号正在等待管理员审核，请耐心等待',
  '账户已被禁用，请联系管理员'
])

export async function refreshTokens(legacyRefreshToken) {
  const body = legacyRefreshToken ? { refresh_token: legacyRefreshToken } : undefined
  const { data } = await authApi.post('/api/auth/refresh', body)
  return data
}

export async function logoutRefreshCookie() {
  return authApi.post('/api/auth/logout')
}

function redirectToLogin() {
  clearBrowserSession()
  if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
    window.location.assign('/login')
  }
}

api.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

let refreshing = null
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config || {}
    const status = error.response?.status
    const detail = error.response?.data?.detail

    if (status === 403 && ACCOUNT_BLOCK_DETAILS.has(detail)) {
      redirectToLogin()
      return Promise.reject(error)
    }

    if (
      status === 401
      && !original._retry
      && !NO_AUTO_REFRESH.has(original.url)
      && getAccessToken()
    ) {
      original._retry = true
      try {
        if (!refreshing) {
          refreshing = refreshTokens()
            .then((data) => {
              setAccessToken(data.access_token)
              return data
            })
            .finally(() => {
              refreshing = null
            })
        }
        const data = await refreshing
        original.headers = original.headers || {}
        original.headers.Authorization = `Bearer ${data.access_token}`
        return api(original)
      } catch (refreshError) {
        const refreshStatus = refreshError?.response?.status
        if (refreshStatus === 401 || refreshStatus === 403) redirectToLogin()
        return Promise.reject(refreshError)
      }
    }
    return Promise.reject(error)
  }
)

export default api
