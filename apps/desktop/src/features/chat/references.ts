import type { Source } from '../../shared/types/api'
import type { Reference } from '../../shared/types/conversations'

export const referenceLabel = (reference: Reference) => reference.title || reference.filename
export const referenceLocation = (reference: Reference) => reference.path || reference.filename
export const referenceDescription = (reference: Reference) =>
  [referenceLabel(reference), referenceLocation(reference)].join('\n')

export function sourceReference(source: Source): Reference {
  return {
    id: source.document_id,
    filename: source.filename,
    ...(source.content_scope === 'full_document' && source.section
      ? { title: source.section }
      : {}),
    ...(source.path ? { path: source.path } : {}),
  }
}
