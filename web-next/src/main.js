import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './assets/base.css'
import './assets/admin.css'
import './assets/candidate.css'

import App from './App.vue'
import router from './router'
import { installToast } from './components/ui'

const app = createApp(App)
app.use(createPinia())
app.use(router)
installToast(app)
app.mount('#app')
