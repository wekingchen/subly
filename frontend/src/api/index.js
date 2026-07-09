import axios from 'axios'

const api = axios.create({ baseURL: '/' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 统一清会话：定向移除令牌（不用 localStorage.clear，避免误伤其它本地项）后跳登录。
// 必须先清 access_token，否则 /login 守卫因 loggedIn 仍为真会把用户反跳回 /dashboard，
// 形成 401 <-> 跳转 死循环。
function clearSession() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  window.location.href = '/login'
}

let refreshing = null
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true
      const rt = localStorage.getItem('refresh_token')
      if (rt) {
        try {
          if (!refreshing) {
            refreshing = axios.post('/api/auth/refresh', { refresh_token: rt })
          }
          const { data } = await refreshing
          refreshing = null
          localStorage.setItem('access_token', data.access_token)
          localStorage.setItem('refresh_token', data.refresh_token)
          original.headers.Authorization = `Bearer ${data.access_token}`
          return api(original)
        } catch (e) {
          refreshing = null
          // 只有 refresh 明确返回 401/403（refresh token 失效）才清会话跳登录；
          // 网络错误 / 超时 / 5xx 只是暂时的，交给调用方（如路由守卫）保留会话、
          // 取消本次导航即可，避免后端短暂不可用就把用户强制登出。
          if (e?.response?.status === 401 || e?.response?.status === 403) {
            clearSession()
          }
          return Promise.reject(e)
        }
      } else {
        // 有 access_token 但没有 refresh_token：无法续期，必须清会话再跳登录，
        // 否则 /login 守卫会因 access_token 仍在而反跳 /dashboard，卡死循环。
        clearSession()
      }
    }
    return Promise.reject(error)
  }
)

export default api
