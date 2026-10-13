<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { MessageSquare, MoreHorizontal, Pencil, Trash2, X } from '@lucide/vue'
import { useAppStore } from '../../app/store'
import { useI18n } from '../../shared/i18n'
import { useChatStore } from './store'
const app = useAppStore(),
  chat = useChatStore(),
  router = useRouter()
const route = useRoute()
const emit = defineEmits<{ navigate: [] }>()
const { t } = useI18n()
const search = ref('')
const items = computed(() =>
  chat
    .list(app.activeLibrary)
    .filter((item) => item.title.toLowerCase().includes(search.value.toLowerCase())),
)
const editing = ref(''),
  draft = ref(''),
  deleting = ref('')
const renameDialog = ref<HTMLDialogElement>(),
  deleteDialog = ref<HTMLDialogElement>(),
  titleInput = ref<HTMLInputElement>()
function select(id: string) {
  chat.select(app.activeLibrary, id)
  emit('navigate')
  void router.push('/')
}
function closeMenu(id: string) {
  document.getElementById(`chat-actions-${id}`)?.hidePopover()
}
async function rename(id: string) {
  closeMenu(id)
  editing.value = id
  draft.value = chat.sessions.find((item) => item.id === id)?.title ?? ''
  renameDialog.value?.showModal()
  await nextTick()
  titleInput.value?.focus()
}
function saveName() {
  chat.rename(editing.value, draft.value)
  renameDialog.value?.close()
}
function requestDelete(id: string) {
  closeMenu(id)
  deleting.value = id
  deleteDialog.value?.showModal()
}
function confirmDelete() {
  chat.remove(deleting.value)
  deleteDialog.value?.close()
}
</script>
<template>
  <section class="conversation-navigation" :aria-label="t('最近对话')">
    <div class="conversation-heading">
      <span>{{ t('最近对话') }}</span>
    </div>
    <input
      class="conversation-search"
      v-model="search"
      :aria-label="t('搜索对话')"
      :placeholder="t('搜索对话…')"
    />
    <p v-if="!items.length" class="conversation-empty">{{ t('还没有对话') }}</p>
    <div class="conversation-items">
      <div
        v-for="item in items"
        :key="item.id"
        class="conversation-item"
        :class="{ active: item.id === chat.activeByLibrary[app.activeLibrary] }"
      >
        <button
          class="conversation-select"
          :aria-current="item.id === chat.activeByLibrary[app.activeLibrary] ? 'true' : undefined"
          @click="select(item.id)"
        >
          <MessageSquare :size="14" /><span>{{ item.title || t('新对话') }}</span>
        </button>
        <button
          class="icon-button conversation-more"
          :aria-label="`${item.title || t('新对话')} · ${t('更多操作')}`"
          :popovertarget="`chat-actions-${item.id}`"
          :style="{ 'anchor-name': `--chat-menu-${item.id}` }"
          type="button"
        >
          <MoreHorizontal :size="15" />
        </button>
        <div
          :id="`chat-actions-${item.id}`"
          class="conversation-popover"
          popover="auto"
          :style="{ 'position-anchor': `--chat-menu-${item.id}` }"
        >
          <button @click="rename(item.id)"><Pencil :size="13" />{{ t('重命名') }}</button
          ><button class="danger" @click="requestDelete(item.id)">
            <Trash2 :size="13" />{{ t('删除对话') }}
          </button>
        </div>
      </div>
    </div>
    <div v-if="chat.deleted" class="undo-chat" role="status">
      {{ t('对话已删除')
      }}<button class="text-button" @click="chat.undoDelete">{{ t('撤销') }}</button>
    </div>
  </section>
  <Teleport to="body">
    <dialog ref="renameDialog" class="action-dialog" :aria-label="t('重命名')">
      <form @submit.prevent="saveName">
        <div class="dialog-heading">
          <h2>{{ t('重命名') }}</h2>
          <button
            class="icon-button"
            type="button"
            :aria-label="t('取消')"
            @click="renameDialog?.close()"
          >
            <X :size="18" />
          </button>
        </div>
        <label for="chat-title">{{ t('对话名称') }}</label
        ><input id="chat-title" ref="titleInput" v-model="draft" maxlength="80" required />
        <div class="dialog-actions">
          <button type="button" class="button secondary" @click="renameDialog?.close()">
            {{ t('取消') }}</button
          ><button class="button primary" :disabled="!draft.trim()">{{ t('保存') }}</button>
        </div>
      </form>
    </dialog>
    <dialog ref="deleteDialog" class="action-dialog" :aria-label="t('删除此对话？')">
      <h2>{{ t('删除此对话？') }}</h2>
      <p>{{ t('删除后可以立即撤销，资料库不会受影响。') }}</p>
      <div class="dialog-actions">
        <button class="button secondary" @click="deleteDialog?.close()">{{ t('取消') }}</button
        ><button class="button destructive" @click="confirmDelete">{{ t('删除') }}</button>
      </div>
    </dialog>
  </Teleport>
</template>
