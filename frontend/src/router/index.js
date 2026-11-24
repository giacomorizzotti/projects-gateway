import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/mini/stores/auth'

import LoginView from '@/mini/views/LoginView.vue'
import Callback from '@/views/Callback.vue'
import Dashboard from '@/views/Dashboard.vue'
import ProjectDetail from '@/views/ProjectDetail.vue'
import Platforms from '@/views/Platforms.vue'
import PlatformDetail from '@/views/PlatformDetail.vue'
import Repositories from '@/views/Repositories.vue'
import Status from '@/views/Status.vue'
import Backups from '@/views/Backups.vue'
import Domains from '@/views/Domains.vue'
import Services from '@/views/Services.vue'
import Settings from '@/views/Settings.vue'
import NotFound from '@/views/NotFound.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    { path: '/projects/:slug', name: 'project', component: ProjectDetail, props: true },
    { path: '/platforms', name: 'platforms', component: Platforms },
    { path: '/platforms/:slug', name: 'platform', component: PlatformDetail, props: true },
    { path: '/repositories', name: 'repositories', component: Repositories },
    { path: '/status', name: 'status', component: Status },
    { path: '/backups', name: 'backups', component: Backups },
    { path: '/domains', name: 'domains', component: Domains },
    { path: '/services', name: 'services', component: Services },
    { path: '/settings', name: 'settings', component: Settings },
    { path: '/login', name: 'login', component: LoginView, props: { redirectRouteName: 'dashboard' }, meta: { public: true } },
    { path: '/callback', name: 'callback', component: Callback, meta: { public: true } },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFound },
  ],
  scrollBehavior(to, from, saved) {
    return saved || { top: 0 }
  },
})

// Everything but login/callback needs a valid token (refreshed only when close to expiry).
router.beforeEach(async (to) => {
  if (to.meta.public) return true
  const auth = useAuthStore()
  if (!auth.accessToken && !auth.refreshToken) return { name: 'login' }
  try {
    return (await auth.ensureValidToken()) ? true : { name: 'login' }
  } catch {
    return { name: 'login' }
  }
})

export default router
