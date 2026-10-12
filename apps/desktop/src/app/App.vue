<script setup lang="ts">
import { onMounted, onBeforeUnmount, computed } from 'vue'
import {
  BookOpen,
  Database,
  Shapes,
  Settings2,
  SquarePen,
  LoaderCircle,
  ShieldCheck,
  PanelLeftClose,
  PanelLeftOpen,
} from '@lucide/vue'
import { useRouter, useRoute } from 'vue-router'
import { useChatStore } from '../features/chat/store'
import ConversationList from '../features/chat/ConversationList.vue'
import { useI18n } from '../shared/i18n'
import { useLayoutStore } from './layout'
import { useAppStore } from './store'

const app = useAppStore()
const chat = useChatStore()
const router = useRouter()
const route = useRoute()
const layout = useLayoutStore()
const idleHome = computed(
  () => route.path === '/' && !chat.current(app.activeLibrary)?.messages.length,
)
function newChat() {
  if (idleHome.value) return
  chat.create(app.activeLibrary)
  void router.push('/')
}
const { t, libraryName } = useI18n()
function shortcuts(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') {
    event.preventDefault()
    newChat()
  }
}
onBeforeUnmount(() => window.removeEventListener('keydown', shortcuts))
onMounted(() => {
  window.addEventListener('keydown', shortcuts)
  void app.initialize()
})
</script>

<template>
  <div class="app-shell" :class="{ 'sidebar-collapsed': layout.sidebarCollapsed }">
    <aside id="app-sidebar" class="sidebar" v-show="!layout.sidebarCollapsed">
      <a href="#/" class="brand"
        ><span class="brand-icon"><BookOpen :size="22" /></span
        ><span>Edge<span class="brand-light"> Assistant</span></span></a
      >
      <div class="workspace-label">{{ t('个人工作空间') }}</div>
      <button class="sidebar-new-chat" :disabled="idleHome" @click="newChat">
        <SquarePen :size="17" />{{ t('新对话') }}<kbd>⌘ N</kbd>
      </button>
      <nav class="navigation" :aria-label="t('主导航')">
        <RouterLink to="/library" active-class="active"
          ><Database :size="19" />{{ t('我的知识库') }}</RouterLink
        >
        <RouterLink to="/semantic" active-class="active"
          ><Shapes :size="19" />{{ t('多模态工作台') }}</RouterLink
        >
      </nav>

      <div class="sidebar-library">
        <label for="active-library" class="eyebrow">{{ t('当前知识库') }}</label>
        <select
          id="active-library"
          :aria-label="t('当前知识库')"
          v-model="app.activeLibrary"
          :disabled="app.loading || !app.health"
        >
          <option v-if="!app.libraries.length" value="default">{{ t('我的知识库') }}</option>
          <option v-for="library in app.libraries" :key="library.id" :value="library.id">
            {{ libraryName(library.id, library.name) }}
          </option>
        </select>
      </div>

      <ConversationList />
      <div class="sidebar-bottom">
        <RouterLink to="/access" active-class="active" class="sidebar-settings"
          ><ShieldCheck :size="17" />{{ t('本地权限') }}</RouterLink
        >
        <RouterLink to="/settings" active-class="active" class="sidebar-settings"
          ><Settings2 :size="17" />{{ t('偏好设置') }}</RouterLink
        >
        <div class="sidebar-footer">
          <span class="status-dot" :class="{ offline: !app.health }"></span
          >{{
            app.loading ? t('正在连接…') : app.health ? t('本地服务已连接') : t('本地服务未连接')
          }}
        </div>
      </div>
    </aside>

    <main class="main-panel">
      <button
        class="icon-button sidebar-toggle"
        type="button"
        aria-controls="app-sidebar"
        :aria-expanded="!layout.sidebarCollapsed"
        :aria-label="t(layout.sidebarCollapsed ? '展开侧栏' : '收起侧栏')"
        :title="t(layout.sidebarCollapsed ? '展开侧栏' : '收起侧栏')"
        @click="layout.toggleSidebar"
      >
        <PanelLeftOpen v-if="layout.sidebarCollapsed" :size="18" /><PanelLeftClose
          v-else
          :size="18"
        />
      </button>
      <div v-if="app.error" role="alert" class="connection-banner">
        {{ app.error
        }}<button class="text-button" @click="app.initialize">{{ t('重新连接') }}</button>
      </div>
      <div v-if="app.loading" class="loading-screen">
        <LoaderCircle class="spin" :size="24" />
        <p>{{ t('正在连接你的知识空间…') }}</p>
      </div>
      <RouterView v-else />
    </main>
  </div>
</template>
