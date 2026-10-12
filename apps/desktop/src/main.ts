import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './app/App.vue'
import ChatView from './features/chat/ChatView.vue'
import SemanticView from './features/semantic/SemanticView.vue'
import LibraryView from './features/library/LibraryView.vue'
import AccessView from './features/access/AccessView.vue'
import SettingsView from './features/settings/SettingsView.vue'
import './app/styles.css'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: ChatView },
    { path: '/semantic', component: SemanticView },
    { path: '/library', component: LibraryView },
    { path: '/access', component: AccessView },
    { path: '/settings', component: SettingsView },
  ],
})
createApp(App).use(createPinia()).use(router).mount('#app')
