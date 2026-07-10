import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../stores/auth'

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

// 内置 SQLite，零配置，数据库始终就绪；首次导航先用 HttpOnly refresh cookie 恢复会话。
router.beforeEach(async (to) => {
  const auth = useAuth()
  try {
    await auth.initialize()
  } catch {
    // 网络 / 5xx 不清退或伪装成未登录；允许目标页加载，后端接口仍会独立保护数据。
    // 用户可在服务恢复后刷新重试，旧迁移凭据也会保留。
    return true
  }

  if (!to.meta.guest && !auth.isLoggedIn) return '/login'
  if (to.meta.guest && auth.isLoggedIn) return '/dashboard'
  if (to.meta.admin && !auth.user?.is_admin) return '/dashboard'
})

export default router
