<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/mini/stores/auth'
import { api } from '@/api'
import Container from '@/mini/components/Container.vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import Space from '@/mini/components/Space.vue'
import LoadingBox from '@/mini/components/LoadingBox.vue'

const route = useRoute()
const auth = useAuthStore()
const problem = ref('')

onMounted(async () => {
  const { code, state, error } = route.query
  if (error || !code || state !== sessionStorage.getItem('pkce_state')) {
    problem.value = 'The login didn’t complete. Please try again.'
    return
  }
  const ok = await auth.handleCallback(code, `${window.location.origin}/callback`)
  if (!ok) {
    problem.value = auth.authError || 'The login didn’t complete. Please try again.'
    return
  }
  // The auth server accepted the login; now check that the gateway knows this account.
  try {
    await api('me/')
  } catch (e) {
    auth.logout()
    problem.value = e.status === 401
      ? 'This account isn’t allowed in the Projects Gateway.'
      : 'The gateway didn’t answer. Please try again in a moment.'
    return
  }
  window.location.replace('/')
})
</script>

<template>
  <Container>
    <Boxes fh class="align-content-start">
      <Box :size="100">
        <Space height="2"/>
        <template v-if="problem">
          <h1 class="m-0">Sign in</h1>
          <p>{{ problem }}</p>
          <RouterLink :to="{ name: 'login' }" class="btn">Back to sign in</RouterLink>
        </template>
        <LoadingBox dark v-else/>
      </Box>
    </Boxes>
  </Container>
</template>
