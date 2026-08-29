import { nextTick } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../stores/auth'

const routes = [
  { path: '/login', component: () => import('../views/Login.vue'), meta: { guest: true, title: '登录' } },
  {
    path: '/',
    component: () => import('../components/Layout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '雷达总览' } },
      { path: 'subscriptions', component: () => import('../views/Subscriptions.vue'), meta: { title: '订阅账本' } },
      { path: 'credit-cards', component: () => import('../views/CreditCards.vue'), meta: { title: '信用卡管理' } },
      { path: 'calendar', component: () => import('../views/Calendar.vue'), meta: { title: '续费与还款日历' } },
      { path: 'reports', component: () => import('../views/Reports.vue'), meta: { title: '支出报表' } },
      { path: 'notifications', component: () => import('../views/Notifications.vue'), meta: { title: '通知中心' } },
      { path: 'logs', component: () => import('../views/Logs.vue'), meta: { title: '实时日志' } },
      { path: 'settings', component: () => import('../views/Settings.vue'), meta: { title: '系统设置' } },
      { path: 'icon-library', component: () => import('../views/IconLibrary.vue'), meta: { admin: true, title: '服务管理' } },
      { path: 'admin-diagnostics', component: () => import('../views/AdminDiagnostics.vue'), meta: { admin: true, title: '数据诊断' } },
      { path: 'users', component: () => import('../views/Users.vue'), meta: { admin: true, title: '用户管理' } }
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

router.afterEach((to, from, failure) => {
  if (failure) return
  document.title = `${to.meta.title || 'Subly'} · Subly`
  if (!from.path || to.path === from.path) return
  nextTick(() => document.querySelector('#main-content h1')?.focus())
})

export default router
