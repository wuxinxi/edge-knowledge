<script setup lang="ts">
import { onMounted, onBeforeUnmount, computed, watch, nextTick, ref } from 'vue'
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
  Home,
  History,
  FolderOpen,
} from '@lucide/vue'
import { useRouter, useRoute } from 'vue-router'
import { useChatStore } from '../features/chat/store'
import ConversationList from '../features/chat/ConversationList.vue'
import TaskCenter from '../features/tasks/TaskCenter.vue'
import { useI18n } from '../shared/i18n'
import { useLayoutStore } from './layout'
import { useAppStore } from './store'

const app = useAppStore()
const chat = useChatStore()
const router = useRouter()
const route = useRoute()
const layout = useLayoutStore()
const sidebar = ref<HTMLElement>()
const railToggle = ref<HTMLButtonElement>()
const activeLibraryName = computed(() => {
  const library = app.libraries.find((item) => item.id === app.activeLibrary)
  return libraryName(app.activeLibrary, library?.name ?? t('我的知识库'))
})
const idleHome = computed(
  () =>
    route.path === '/' &&
    !!chat.current(app.activeLibrary) &&
    !chat.current(app.activeLibrary)!.messages.length,
)
function newChat() {
  if (idleHome.value || chat.loading) return
  chat.create(app.activeLibrary)
  closeOnNarrowScreen()
  void router.push('/')
}
const { t, libraryName } = useI18n()
async function revealSidebar(target: 'history' | 'library') {
  layout.sidebarCollapsed = false
  await nextTick()
  sidebar.value
    ?.querySelector<HTMLElement>(target === 'history' ? '.conversation-search' : '#active-library')
    ?.focus()
}
async function closeSidebar() {
  layout.sidebarCollapsed = true
  await nextTick()
  railToggle.value?.focus()
}
function toggleSidebar() {
  if (layout.sidebarCollapsed) layout.sidebarCollapsed = false
  else void closeSidebar()
}
function closeOnNarrowScreen() {
  if (window.matchMedia('(max-width: 760px)').matches) layout.sidebarCollapsed = true
}
watch(() => route.path, closeOnNarrowScreen)
function shortcuts(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') {
    event.preventDefault()
    newChat()
  }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'b') {
    event.preventDefault()
    toggleSidebar()
  }
  if (
    event.key === 'Escape' &&
    !layout.sidebarCollapsed &&
    window.matchMedia('(max-width: 760px)').matches &&
    !document.querySelector('dialog[open], [popover]:popover-open')
  ) {
    void closeSidebar()
  }
}
watch(
  () => app.activeLibrary,
  (library) => chat.rememberLibrary(library),
)
onBeforeUnmount(() => window.removeEventListener('keydown', shortcuts))
onMounted(() => {
  window.addEventListener('keydown', shortcuts)
  void (async () => {
    await app.initialize()
    await chat.initialize()
    if (chat.lastLibrary && app.libraries.some((item) => item.id === chat.lastLibrary))
      app.activeLibrary = chat.lastLibrary
  })()
})
</script>

<template>
  <div class="app-shell" :class="{ 'sidebar-collapsed': layout.sidebarCollapsed }">
    <nav class="app-rail" :aria-label="t('主导航')">
      <RouterLink
        to="/"
        exact-active-class="active"
        class="rail-button rail-home"
        :aria-label="t('本地助手')"
      >
        <Home :size="21" /><span class="rail-tooltip" aria-hidden="true">{{ t('本地助手') }}</span>
      </RouterLink>
      <button
        v-show="layout.sidebarCollapsed"
        class="rail-button rail-new-chat"
        :aria-label="t('新对话')"
        :disabled="idleHome || chat.loading"
        @click="newChat"
      >
        <SquarePen :size="20" /><span class="rail-tooltip" aria-hidden="true"
          >{{ t('新对话') }} · ⌘ N</span
        >
      </button>
      <RouterLink
        to="/library"
        active-class="active"
        class="rail-button"
        :aria-label="t('我的知识库')"
      >
        <Database :size="20" /><span class="rail-tooltip" aria-hidden="true">{{
          t('我的知识库')
        }}</span>
      </RouterLink>
      <RouterLink
        to="/semantic"
        active-class="active"
        class="rail-button"
        :aria-label="t('多模态工作台')"
      >
        <Shapes :size="20" /><span class="rail-tooltip" aria-hidden="true">{{
          t('多模态工作台')
        }}</span>
      </RouterLink>
      <span class="rail-divider" aria-hidden="true"></span>
      <button
        class="rail-button"
        :aria-label="`${t('当前知识库')} · ${activeLibraryName}`"
        aria-controls="app-sidebar"
        :aria-expanded="!layout.sidebarCollapsed"
        @click="revealSidebar('library')"
      >
        <FolderOpen :size="20" /><span class="rail-tooltip" aria-hidden="true"
          >{{ t('当前知识库') }} · {{ activeLibraryName }}</span
        >
      </button>
      <button
        class="rail-button"
        :aria-label="t('最近对话')"
        aria-controls="app-sidebar"
        :aria-expanded="!layout.sidebarCollapsed"
        @click="revealSidebar('history')"
      >
        <History :size="20" /><span class="rail-tooltip" aria-hidden="true">{{
          t('最近对话')
        }}</span>
      </button>
      <div class="rail-bottom">
        <TaskCenter />
        <RouterLink
          to="/access"
          active-class="active"
          class="rail-button"
          :aria-label="t('本地权限')"
        >
          <ShieldCheck :size="20" /><span class="rail-tooltip" aria-hidden="true">{{
            t('本地权限')
          }}</span>
        </RouterLink>
        <RouterLink
          to="/settings"
          active-class="active"
          class="rail-button"
          :aria-label="t('偏好设置')"
        >
          <Settings2 :size="20" /><span class="rail-tooltip" aria-hidden="true">{{
            t('偏好设置')
          }}</span>
        </RouterLink>
        <span class="rail-divider" aria-hidden="true"></span>
        <button
          ref="railToggle"
          class="rail-button sidebar-toggle"
          type="button"
          aria-controls="app-sidebar"
          :aria-expanded="!layout.sidebarCollapsed"
          :aria-label="t(layout.sidebarCollapsed ? '展开侧栏' : '收起侧栏')"
          @click="toggleSidebar"
        >
          <PanelLeftOpen v-if="layout.sidebarCollapsed" :size="20" /><PanelLeftClose
            v-else
            :size="20"
          />
          <span class="rail-tooltip" aria-hidden="true"
            >{{ t(layout.sidebarCollapsed ? '展开侧栏' : '收起侧栏') }} · ⌘ B</span
          >
        </button>
      </div>
    </nav>
    <button
      v-if="!layout.sidebarCollapsed"
      class="sidebar-backdrop"
      :aria-label="t('收起侧栏')"
      @click="closeSidebar"
    ></button>
    <aside
      ref="sidebar"
      id="app-sidebar"
      class="sidebar"
      v-show="!layout.sidebarCollapsed"
      :aria-label="t('个人工作空间')"
    >
      <div class="sidebar-heading">
        <a href="#/" class="brand"
          ><span class="brand-icon"><BookOpen :size="22" /></span
          ><span>Edge<span class="brand-light"> Assistant</span></span></a
        >
        <button class="icon-button sidebar-close" :aria-label="t('收起侧栏')" @click="closeSidebar">
          <PanelLeftClose :size="17" />
        </button>
      </div>
      <div class="workspace-label">{{ t('个人工作空间') }}</div>
      <button class="sidebar-new-chat" :disabled="idleHome || chat.loading" @click="newChat">
        <SquarePen :size="17" />{{ t('新对话') }}<kbd>⌘ N</kbd>
      </button>
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

      <ConversationList @navigate="closeOnNarrowScreen" />
      <div class="sidebar-bottom">
        <div class="sidebar-footer">
          <span class="status-dot" :class="{ offline: !app.health }"></span
          >{{
            app.loading ? t('正在连接…') : app.health ? t('本地服务已连接') : t('本地服务未连接')
          }}
        </div>
      </div>
    </aside>

    <main class="main-panel">
      <div v-if="app.error" role="alert" class="connection-banner">
        {{ app.error
        }}<button class="text-button" @click="app.initialize">{{ t('重新连接') }}</button>
      </div>
      <div v-if="app.loading || chat.loading" class="loading-screen">
        <LoaderCircle class="spin" :size="24" />
        <p>{{ t('正在连接你的知识空间…') }}</p>
      </div>
      <RouterView v-else />
    </main>
  </div>
</template>
