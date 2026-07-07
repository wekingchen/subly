<template>
  <div class="shell">
    <!-- 移动端顶部栏 -->
    <header class="topbar">
      <button ref="hambRef" class="hamb" @click="openDrawer" :aria-expanded="drawer ? 'true' : 'false'" aria-controls="mobile-sidebar" :aria-label="t('nav.menu')">☰</button>
      <div class="brand sm"><span class="brand-mark"><img src="/brand-icon.png" alt="" /></span><span>Subly</span></div>
      <div style="width:44px"></div>
    </header>

    <!-- 遮罩（移动端抽屉打开时） -->
    <div v-if="drawer" class="drawer-mask" @click="drawer = false"></div>

    <aside id="mobile-sidebar" ref="drawerRef" class="sidebar" :class="{ open: drawer }" :aria-label="t('nav.menu')" tabindex="-1">
      <div class="brand-block">
        <div class="brand"><span class="brand-mark"><img src="/brand-icon.png" alt="" /></span><span>Subly</span></div>
        <div class="brand-tag"><span class="signal-dot"></span>{{ t('nav.brandTag') }}</div>
      </div>
      <nav class="nav-list" :aria-label="t('nav.menu')" @click="closeDrawer">
        <section v-for="group in navGroups" :key="group.title" class="nav-group">
          <div class="nav-group-title">{{ t(group.title) }}</div>
          <router-link v-for="it in group.items" :key="it.to" :to="it.to" class="nav-card">
            <span class="nav-ico" v-html="icon(it.key)"></span>
            <span class="nav-label">{{ t(it.label) }}</span>
            <span class="nav-arrow">›</span>
          </router-link>
        </section>
      </nav>
      <div class="spacer"></div>
      <div class="user" v-if="auth.user">
        <div class="uname">{{ auth.user.username }}</div>
        <a href="#" @click.prevent="logout">🚪 {{ t('nav.logout') }}</a>
      </div>
    </aside>

    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useAuth } from '../stores/auth'
import { icon } from '../icons'
import { useBodyLock } from '../composables/useBodyLock'

const { t } = useI18n()
const auth = useAuth()
const router = useRouter()
const drawer = ref(false)
const hambRef = ref(null)
const drawerRef = ref(null)

function openDrawer() {
  drawer.value = true
}
function closeDrawer() {
  drawer.value = false
}
useBodyLock(drawer, 'layout-drawer')
watch(drawer, (open) => {
  nextTick(() => (open ? drawerRef.value : hambRef.value)?.focus?.())
})
function onKey(e) {
  if (e.key === 'Escape' && drawer.value) closeDrawer()
}
if (typeof window !== 'undefined') {
  window.addEventListener('keydown', onKey)
}
onBeforeUnmount(() => {
  if (typeof window !== 'undefined') window.removeEventListener('keydown', onKey)
})

const navGroups = computed(() => {
  const groups = [
    {
      title: 'nav.groupWorkspace',
      items: [
        { to: '/dashboard', key: 'dashboard', label: 'nav.dashboard' },
        { to: '/subscriptions', key: 'subscriptions', label: 'nav.subscriptions' },
        { to: '/calendar', key: 'calendar', label: 'nav.calendar' },
        { to: '/reports', key: 'reports', label: 'nav.reports' }
      ]
    },
    {
      title: 'nav.groupSystem',
      items: [
        { to: '/notifications', key: 'notifications', label: 'nav.notifications' },
        { to: '/logs', key: 'logs', label: 'nav.logs' },
        { to: '/settings', key: 'settings', label: 'nav.settings' }
      ]
    }
  ]
  if (auth.user?.is_admin) {
    groups.push({
      title: 'nav.groupAdmin',
      items: [
        { to: '/icon-library', key: 'iconLibrary', label: 'nav.iconLibrary' },
        { to: '/admin-diagnostics', key: 'diagnostics', label: 'nav.diagnostics' },
        { to: '/users', key: 'users', label: 'nav.users' }
      ]
    })
  }
  return groups
})

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.shell { display: flex; min-height: 100vh; }
.sidebar { width: 240px; background: color-mix(in srgb, var(--surface) 92%, var(--radar-panel)); border-right: 1px solid var(--border);
  display: flex; flex-direction: column; padding: 18px 14px; position: sticky; top: 0; height: 100vh; z-index: 50;
  box-shadow: inset -1px 0 0 color-mix(in srgb, var(--primary) 12%, transparent); }
.brand-block { margin-bottom: 22px; padding: 10px 8px 14px; border-bottom: 1px solid var(--border); }
.brand { display: flex; align-items: center; gap: 8px; font-weight: 800; font-size: 18px; letter-spacing: -.04em;
  color: var(--text); }
.brand-mark { width: 28px; height: 28px; border-radius: 9px; display: inline-flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, var(--signal-cyan), var(--primary)); color: #06101f; font-weight: 900;
  box-shadow: 0 0 22px color-mix(in srgb, var(--signal-cyan) 42%, transparent); overflow: hidden; }
.brand-mark img { width: 100%; height: 100%; display: block; object-fit: cover; border-radius: inherit; }
.brand-tag { margin-top: 7px; display: flex; align-items: center; gap: 7px; color: var(--text-soft); font-size: 11px;
  text-transform: uppercase; letter-spacing: .12em; }
.nav-list { display: flex; flex-direction: column; gap: 16px; }
.nav-group { display: flex; flex-direction: column; gap: 6px; }
.nav-group + .nav-group { padding-top: 2px; }
.nav-group-title { display: flex; align-items: center; gap: 8px; padding: 0 8px 2px 12px;
  color: var(--text-soft); font-size: 11px; font-weight: 800; letter-spacing: .16em; }
.nav-group-title::before { content: ''; width: 16px; height: 1px; border-radius: 999px;
  background: linear-gradient(90deg, var(--signal-cyan), transparent);
  box-shadow: 0 0 10px color-mix(in srgb, var(--signal-cyan) 45%, transparent); }
.nav-card { position: relative; display: grid; grid-template-columns: 30px minmax(0, 1fr) 12px; align-items: center; gap: 10px;
  min-height: 44px; padding: 7px 11px 7px 12px; border-radius: 11px;
  color: var(--text); font-size: 14px; border: 1px solid transparent; background: transparent;
  transition: transform .15s ease, background .15s ease, box-shadow .2s ease, border-color .15s ease, color .15s ease; }
.nav-card::before { content: ''; width: 3px; height: 0; border-radius: 999px; position: absolute; left: 0; top: 50%; transform: translateY(-50%);
  background: var(--signal-cyan); box-shadow: 0 0 14px color-mix(in srgb, var(--signal-cyan) 60%, transparent); transition: height .18s ease; }
.nav-ico { width: 30px; height: 30px; border-radius: 9px; display: flex; align-items: center;
  justify-content: center; background: var(--surface-2); border: 1px solid var(--border);
  flex-shrink: 0; transition: transform .2s ease, color .15s ease, border-color .15s ease; color: var(--text-soft); }
.nav-ico :deep(svg) { width: 17px; height: 17px; }
.nav-label { min-width: 0; font-weight: 650; letter-spacing: .02em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nav-arrow { color: var(--text-soft); opacity: 0; transform: translateX(-4px); transition: all .2s ease; }
.nav-card:hover { transform: translateX(3px); background: color-mix(in srgb, var(--primary) 9%, transparent); border-color: color-mix(in srgb, var(--primary) 24%, transparent); }
.nav-card:hover .nav-ico { transform: scale(1.06); color: var(--primary); border-color: color-mix(in srgb, var(--primary) 32%, var(--border)); }
.nav-card:hover .nav-arrow { opacity: 1; transform: translateX(0); }
.nav-card.router-link-active { background: color-mix(in srgb, var(--signal-cyan) 10%, var(--surface));
  color: var(--primary); border-color: color-mix(in srgb, var(--signal-cyan) 34%, var(--border)); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--signal-cyan) 10%, transparent); }
.nav-card.router-link-active::before { height: 26px; }
.nav-card.router-link-active .nav-ico { color: var(--signal-cyan); border-color: color-mix(in srgb, var(--signal-cyan) 48%, transparent); background: color-mix(in srgb, var(--signal-cyan) 10%, var(--surface-2)); }
.nav-card.router-link-active .nav-arrow { opacity: 1; transform: translateX(0); color: var(--primary); }
.spacer { flex: 1; }
.user { font-size: 13px; color: var(--text-soft); border-top: 1px solid var(--border); padding-top: 12px; }
.user .uname { font-weight: 800; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.user a { display: inline-flex; align-items: center; gap: 4px; margin-top: 8px; }
.content { flex: 1; padding: 26px 32px; max-width: 1200px; width: 100%; }

/* 顶部栏 + 抽屉遮罩仅移动端出现 */
.topbar { display: none; }
.drawer-mask { display: none; }

@media (max-width: 720px) {
  .shell { flex-direction: column; }
  .topbar { display: flex; align-items: center; justify-content: space-between;
    position: sticky; top: 0; z-index: 45; background: var(--surface);
    border-bottom: 1px solid var(--border); padding: 10px 14px; }
  .topbar .brand.sm { margin: 0; font-size: 15px; }
  .hamb { width: 44px; height: 44px; border: none; background: transparent;
    font-size: 20px; color: var(--text); cursor: pointer; border-radius: 10px; }
  .topbar { padding-top: calc(10px + env(safe-area-inset-top)); padding-bottom: calc(10px + env(safe-area-inset-bottom)); }
  .drawer-mask { display: block; position: fixed; inset: 0; background: rgba(15,18,35,.5);
    z-index: 48; }
  .sidebar { position: fixed; top: 0; left: 0; height: 100dvh; width: min(82vw, 280px);
    transform: translateX(-110%); transition: transform .25s ease; box-shadow: var(--shadow-lg);
    overflow-y: auto; -webkit-overflow-scrolling: touch; padding-bottom: calc(18px + env(safe-area-inset-bottom)); outline: none; }
  .sidebar.open { transform: translateX(0); }
  .nav-list { gap: 14px; }
  .nav-card { min-height: 48px; padding-block: 9px; }
  .nav-label { white-space: normal; line-height: 1.25; }
  .content { padding: 16px 14px; min-width: 0; }
}
</style>
