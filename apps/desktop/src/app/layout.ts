import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
const key = 'edge-assistant.layout.v1'
export const useLayoutStore = defineStore('layout', () => {
  let saved = false
  try {
    saved = JSON.parse(localStorage.getItem(key) ?? 'null')?.sidebarCollapsed === true
  } catch {
    /* optional UI persistence */
  }
  const sidebarCollapsed = ref(saved)
  watch(sidebarCollapsed, (value) => {
    try {
      localStorage.setItem(key, JSON.stringify({ sidebarCollapsed: value }))
    } catch {
      /* layout remains usable without storage */
    }
  })
  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }
  return { sidebarCollapsed, toggleSidebar }
})
