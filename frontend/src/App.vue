<script setup>
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { IconoirProvider } from '@iconoir/vue'
import Header from '@/mini/components/Header.vue'
import HeaderMenu from '@/mini/components/HeaderMenu.vue'
import Container from '@/mini/components/Container.vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import Space from '@/mini/components/Space.vue'
import Sheet from '@/mini/components/Sheet.vue'
import Aside from '@/mini/components/Aside.vue'
import Main from '@/mini/components/Main.vue'
import Menu from '@/mini/components/Menu.vue'
import Loader from '@/mini/components/Loader.vue'
import Top from '@/mini/components/Top.vue'
import MessageBox from '@/mini/components/MessageBox.vue'
import { useAuthStore } from '@/mini/stores/auth'
import { useStatusStore } from '@/stores/status'
import StatusBox from '@/components/StatusBox.vue'
import { useDashboardFilters } from '@/composables/useDashboardFilters'
import { useScrollState } from '@/mini/composables/useScrollState'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const status = useStatusStore()
// What needs attention, above every page: not on the Status page, which lists it all, and not
// signed out (the store keeps its last data after a sign-out).
const showStatusBox = computed(() =>
  auth.isAuthenticated && route.name !== 'status' && status.problems.length > 0)
// Main clears the fixed header for every page, but mini's LoginView already does it itself
// (spaceTopBot): on the login page Main adds no space of its own, or the gap is doubled.
const mainSpacing = computed(() => route.name !== 'login')
// The logo goes home to an unfiltered dashboard, even when it's already open.
const dashboardFilters = useDashboardFilters()
// 'top' or 'scrolled', as the header's own state: the menu is inverted (white) only at the
// top, over the black header. (mini's invert="top" adds a class its CSS doesn't style yet.)
const { scrollClass } = useScrollState()

const menuItems = computed(() => auth.isAuthenticated ? [
  { title: 'Dashboard', routeName: 'dashboard' },
  { title: status.problems.length ? `Status (${status.problems.length})` : 'Status', routeName: 'status' },
  { title: 'Platforms', routeName: 'platforms' },
  { title: 'Domains', routeName: 'domains' },
  { title: 'Repositories', routeName: 'repositories' },
  { title: 'Services', routeName: 'services' },
  { title: 'Backups', routeName: 'backups' },
  { title: 'Settings', routeName: 'settings' },
] : [])

// If the session ends (refresh token rejected), go back to the login page.
watch(() => auth.isAuthenticated, (isAuth, wasAuth) => {
  if (wasAuth && !isAuth) router.push({ name: 'login' })
})

// The status dots on every page: read once signed in, then every minute while the tab is
// visible (the store skips a read younger than a minute).
watch(() => auth.isAuthenticated, isAuth => { if (isAuth) status.load() }, { immediate: true })
let statusTimer = null
onMounted(() => {
  statusTimer = setInterval(() => {
    if (auth.isAuthenticated && document.visibilityState === 'visible') status.load()
  }, 60_000)
})
onUnmounted(() => clearInterval(statusTimer))

function logout() {
  auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <IconoirProvider>
    <Loader/>
    <Top/>
    <MessageBox/>
    <Sheet>
      <Header class="top-black scroll-color">
        <Container>
          <Boxes class="justify-content-between align-items-center">
            <Box class="brand">
              <RouterLink :to="{ name: 'dashboard' }" class="flex align-items-center" @click="dashboardFilters.reset()">
                <img src="/favicon.svg" class="header-logo me-1" alt="" width="40" height="40"/>
                <h3 class="site-title m-0 p">Projects Gateway</h3>
              </RouterLink>
            </Box>
            <HeaderMenu invert/>
          </Boxes>
        </Container>
      </Header>
      <Main :class="['black-bg', { 'space-top-bot': mainSpacing }]">
        <Space v-if="mainSpacing"/>
        <Container v-if="showStatusBox">
          <Boxes>
            <Box :size="100" class="fb-bg">
              <h3 class="S light grey-text mt-0 mb-05">Status</h3>
              <StatusBox/>
            </Box>
          </Boxes>
        </Container>
        <RouterView/>
      </Main>
      <Aside side="right">
        <Menu id="main-menu" :menuCloseOnClick="true" :menuItems="menuItems"/>
        <Menu id="user-menu">
          <li class="item" v-if="auth.isAuthenticated"><a href="#" @click.prevent="logout">Sign out</a></li>
          <li class="item" v-else><RouterLink :to="{ name: 'login' }">Sign in</RouterLink></li>
        </Menu>
      </Aside>
    </Sheet>
  </IconoirProvider>
</template>
