import type { Message, Reference } from '../../shared/types/conversations'
import { sourceReference } from './references'

/** Candidate document context comes from saved evidence, not keywords in a question.
 * It is a hint to the planner. Only an explicit use_context plan activates its scope.
 */
export function conversationDocuments(messages: Message[]): Reference[] {
  const last = messages.at(-1)
  if (
    last?.role !== 'assistant' ||
    last.status !== 'complete' ||
    last.error ||
    last.resultKind === 'clarification' ||
    last.resultKind === 'catalog' ||
    last.resultKind === 'comparison'
  )
    return []
  const documents = new Map(
    last.sources
      .filter((source) => !source.kind || source.kind === 'document')
      .map((source) => [source.document_id, sourceReference(source)]),
  )
  return documents.size <= 10 ? [...documents.values()] : []
}
