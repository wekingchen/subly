import { createRouter, createWebHistory } from 'vue-router'
import api from '../api'

const routes = [
  { path: '/login', component: () => import('../views/Login.vue'), meta: { guest: true } },
  {
    path: '/',
    component: () => import('../components/Layout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', component: () => import('../views/Dashboard.vue') },
      { path: 'subscriptions', component: () => import('../views/Subscriptions.vue') },
      { path: 'calendar', component: () => import('../views/Calendar.vue') },
      { path: 'reports', component: () => import('../views/Reports.vue') },
      { path: 'notifications', component: () => import('../views/Notifications.vue') },
      { path: 'logs', component: () => import('../views/Logs.vue') },
      { path: 'settings', component: () => import('../views/Settings.vue') },
      { path: 'icon-library', component: () => import('../views/IconLibrary.vue'), meta: { admin: true } },
      { path: 'admin-diagnostics', component: () => import('../views/AdminDiagnostics.vue'), meta: { admin: true } },
      { path: 'users', component: () => import('../views/Users.vue'), meta: { admin: true } }
    ]
  }
]

const router = createRouter({ history: createWebHistory(), routes })

// 内置 SQLite，零配置，数据库始终就绪，无需再检测「是否已安装」
router.beforeEach(async (to, from) => {
  const loggedIn = !!localStorage.getItem('access_token')
  if (!to.meta.guest && !loggedIn) return '/login'
  if (to.meta.guest && loggedIn) return '/dashboard'
  if (to.meta.admin) {
    try {
      const { data } = await api.get('/api/auth/me')
      if (!data?.is_admin) return '/dashboard'
    } catch (err) {
      // 仅在确认鉴权失败时清退会话；网络抖动 / 5xx 不应强制登出，否则后端短暂
      // 不稳定会让每次进入 admin 页都变成登出循环。
      const status = err?.response?.status
      if (status === 401 || status === 403) {
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        return '/login'
      }
      // 未知错误（网络 / 5xx）：保留会话。从已有页面进入则中止导航留在原页；
      // 若是首次导航（from 为初始 START_LOCATION），中止会停在空白根视图，故重定向
      // 到 /dashboard，让用户至少落到可见页面，而不是卡在空白屏。
      if (from.matched.length === 0) return '/dashboard'
      return false
    }
  }
})

export default router
