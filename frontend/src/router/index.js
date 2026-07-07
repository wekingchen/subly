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
router.beforeEach(async (to) => {
  const loggedIn = !!localStorage.getItem('access_token')
  if (!to.meta.guest && !loggedIn) return '/login'
  if (to.meta.guest && loggedIn) return '/dashboard'
  if (to.meta.admin) {
    try {
      const { data } = await api.get('/api/auth/me')
      if (!data?.is_admin) return '/dashboard'
    } catch {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      return '/login'
    }
  }
})

export default router
