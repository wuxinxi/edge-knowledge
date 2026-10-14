<script setup lang="ts">
import { SearchX, Pencil, ArrowRight } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import type { Reference } from './store'
import { useI18n } from '../../shared/i18n'
defineProps<{ references: Reference[]; showEdit: boolean; canEdit: boolean; hasDraft: boolean }>()
const emit = defineEmits<{ edit: [] }>()
const { t } = useI18n()
</script>
<template>
  <section class="empty-search-result" :aria-label="t('暂未找到匹配资料')">
    <span class="empty-search-icon"><SearchX :size="20" /></span>
    <div class="empty-search-body">
      <h3>{{ t('暂未找到匹配资料') }}</h3>
      <p>{{ t('试试文件名、笔记标题或几个关键词，也可以确认所需资料是否已经导入。') }}</p>
      <div class="empty-search-scope">
        <span>{{ t('检索范围') }}</span>
        <span v-if="!references.length">{{ t('会话知识库') }}</span>
        <span v-else :title="references.map((item) => item.filename).join(' · ')">
          {{ t('仅引用资料') }} ·
          {{
            references
              .map((item) => item.filename)
              .slice(0, 3)
              .join(' · ')
          }}
          <template v-if="references.length > 3"> · +{{ references.length - 3 }}</template>
        </span>
      </div>
      <div class="empty-search-actions">
        <button
          v-if="showEdit"
          type="button"
          class="button secondary"
          :disabled="!canEdit"
          @click="emit('edit')"
        >
          <Pencil :size="13" />{{ t('修改问题') }}
        </button>
        <RouterLink to="/library" class="text-button"
          >{{ t('查看资料库') }}<ArrowRight :size="13"
        /></RouterLink>
      </div>
      <p v-if="showEdit && hasDraft" class="empty-search-draft-note">
        {{ t('输入框已有草稿，可以直接继续修改。') }}
      </p>
    </div>
  </section>
</template>
