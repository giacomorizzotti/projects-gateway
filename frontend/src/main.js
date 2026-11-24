import './assets/main.scss'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import SignInUnavailable from './views/SignInUnavailable.vue'
import { loadAuthConfig } from '@/config/auth'

// The provider's endpoints first: the router's first navigation (started by app.use(router))
// already needs them, to refresh a token or to sign in.
loadAuthConfig().then(
  () => {
    const app = createApp(App)
    app.use(createPinia())
    app.use(router)
    app.mount('#mini')
  },
  (error) => {
    console.error(error)
    createApp(SignInUnavailable).mount('#mini')
  },
)
