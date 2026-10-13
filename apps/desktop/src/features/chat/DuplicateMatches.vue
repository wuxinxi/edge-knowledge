<script setup lang="ts">
import { FileText, CheckCheck } from '@lucide/vue'
import type { DuplicateComparison } from '../../shared/types/api'
import { useI18n } from '../../shared/i18n'
import SourceContent from './SourceContent.vue'
defineProps<{ pairs: DuplicateComparison[]; library: string }>()
const { t } = useI18n()
</script>
<template>
  <section class="duplicate-matches" :aria-label="t('重复内容对比')">
    <article
      v-for="(pair, index) in pairs"
      :key="`${pair.left.document_id}:${pair.right.document_id}`"
      class="duplicate-match"
    >
      <header class="duplicate-match-heading">
        <strong>{{ t('候选') }} {{ index + 1 }}</strong>
        <span class="duplicate-match-score"
          ><CheckCheck v-if="pair.exact" :size="13" />{{
            t(pair.exact ? '内容一致' : pair.body_exact ? '正文一致' : '相似内容')
          }}
          · {{ t('相似度') }} {{ pair.score.toFixed(2) }}</span
        >
      </header>
      <div class="duplicate-match-columns">
        <section
          v-for="(source, side) in [pair.left, pair.right]"
          :key="source.document_id"
          class="duplicate-match-side"
          :aria-label="`${t(side === 0 ? '左侧笔记' : '右侧笔记')} ${source.filename}`"
        >
          <header>
            <FileText :size="15" /><strong :title="source.filename">{{ source.filename }}</strong>
          </header>
          <p
            v-if="source.path && source.path !== source.filename"
            class="duplicate-source-path"
            :title="source.path"
          >
            {{ source.path }}
          </p>
          <SourceContent :source="source" :library="library" />
        </section>
      </div>
    </article>
  </section>
</template>
<style>
.duplicate-matches {
  display: grid;
  gap: 18px;
  margin-top: 20px;
}
.duplicate-match {
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
  background: var(--surface);
}
.duplicate-match-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
  font-size: 12px;
}
.duplicate-match-score {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
}
.duplicate-match-columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}
.duplicate-match-side {
  min-width: 0;
  padding: 16px;
}
.duplicate-match-side + .duplicate-match-side {
  border-left: 1px solid var(--line);
}
.duplicate-match-side > header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  font-size: 13px;
}
.duplicate-match-side > header > strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.duplicate-source-path {
  margin: -4px 0 14px;
  overflow-wrap: anywhere;
  font-size: 11px;
  color: var(--text-muted);
}
.duplicate-match-side .source-document-excerpt {
  max-height: 260px;
  overflow: auto;
}
@media (max-width: 760px) {
  .duplicate-match-columns {
    grid-template-columns: minmax(0, 1fr);
  }
  .duplicate-match-side + .duplicate-match-side {
    border-left: 0;
    border-top: 1px solid var(--line);
  }
}
</style>
