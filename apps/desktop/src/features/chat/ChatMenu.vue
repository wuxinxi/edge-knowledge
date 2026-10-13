<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Ellipsis } from '@lucide/vue'
const props = defineProps<{ label: string; disabled?: boolean }>()
const menu = ref<HTMLDetailsElement>()
function close() {
  if (menu.value) menu.value.open = false
}
function dismiss(event: PointerEvent) {
  if (!menu.value?.contains(event.target as Node)) close()
}
function escape() {
  if (!menu.value?.open) return
  close()
  menu.value?.querySelector<HTMLElement>('summary')?.focus()
}
onMounted(() => document.addEventListener('pointerdown', dismiss))
onBeforeUnmount(() => document.removeEventListener('pointerdown', dismiss))
watch(
  () => props.disabled,
  (value) => {
    if (value) close()
  },
)
</script>
<template>
  <details ref="menu" class="chat-menu" @keydown.esc.prevent="escape">
    <summary
      :aria-label="label"
      :aria-disabled="disabled || undefined"
      :tabindex="disabled ? -1 : 0"
      @click="disabled && $event.preventDefault()"
    >
      <Ellipsis :size="17" /><span>{{ label }}</span>
    </summary>
    <div class="chat-menu-items" @click="close"><slot /></div>
  </details>
</template>
<style>
.chat-menu {
  position: relative;
  font-size: var(--text-caption);
}
.chat-menu > summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  cursor: pointer;
  list-style: none;
  border-radius: 7px;
  padding: 5px 7px;
}
.chat-menu > summary::-webkit-details-marker {
  display: none;
}
.chat-menu > summary:hover,
.chat-menu[open] > summary {
  background: var(--hover);
  color: var(--text);
}
.chat-menu > summary[aria-disabled='true'] {
  opacity: 0.4;
  cursor: default;
}
.chat-menu-items {
  position: absolute;
  bottom: calc(100% + 8px);
  right: 0;
  z-index: 35;
  width: 200px;
  padding: 5px;
  background: var(--surface);
  border: 1px solid var(--line-strong);
  box-shadow: var(--shadow-float);
  border-radius: 10px;
}
.chat-menu-items > button {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px !important;
  text-align: left;
  justify-content: flex-start;
  border: 0;
  background: transparent;
  border-radius: 6px;
  font-size: var(--text-caption);
  color: var(--text-secondary);
}
.chat-menu-items > button:hover {
  background: var(--hover);
  color: var(--text);
}
.page-header .chat-menu-items {
  top: calc(100% + 8px);
  bottom: auto;
}
</style>
