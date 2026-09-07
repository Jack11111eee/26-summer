import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './assets/base.css'
import './assets/admin.css'
import './assets/candidate.css'

import App from './App.vue'
import router from './router'
import { installToast } from './components/ui'
import { clip } from './directives/clip'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.directive('clip', clip)
installToast(app)
app.mount('#app')
