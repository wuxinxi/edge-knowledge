<script setup lang="ts">
import { Check, Sun, Moon, Monitor } from '@lucide/vue'
import { useI18n } from '../../shared/i18n'
defineProps<{ option: 'system' | 'light' | 'dark'; selected: boolean }>()
defineEmits<{ select: [] }>()
const { t } = useI18n()
</script>
<template>
  <button
    type="button"
    class="theme-option"
    :class="{ selected }"
    :aria-pressed="selected"
    @click="$emit('select')"
  >
    <span class="theme-preview" :class="option" aria-hidden="true">
      <span class="mini-titlebar"><i></i><i></i><i></i></span>
      <span class="mini-workspace"
        ><span class="mini-rail"><i></i><i></i><i></i><i></i></span
        ><span class="mini-sidebar"><i class="mini-logo"></i><i></i><i></i><i></i></span
        ><span class="mini-content"
          ><i class="mini-heading"></i><i class="mini-line long"></i><i class="mini-line"></i
          ><span class="mini-answer"><i></i><i></i></span
          ><span class="mini-composer"><i></i><b></b></span></span
      ></span>
    </span>
    <span class="theme-option-label"
      ><span
        ><Monitor v-if="option === 'system'" :size="14" /><Sun
          v-else-if="option === 'light'"
          :size="14"
        /><Moon v-else :size="14" />{{
          t(option === 'system' ? '跟随系统' : option === 'light' ? '浅色' : '深色')
        }}</span
      ><span class="theme-check"><Check v-if="selected" :size="11" /></span
    ></span>
  </button>
</template>
