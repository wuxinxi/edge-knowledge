<script setup lang="ts">
import AccessSettings from './AccessSettings.vue'
import { useI18n } from '../../shared/i18n'
const { t } = useI18n()
</script>
<template>
  <section class="standard-page">
    <header class="page-header">
      <div>
        <h1>{{ t('本地权限') }}</h1>
        <p class="page-subtitle">{{ t('清楚了解访问范围，安心使用本地助手') }}</p>
      </div>
    </header>
    <div class="page-content access-page-content"><AccessSettings /></div>
  </section>
</template>
