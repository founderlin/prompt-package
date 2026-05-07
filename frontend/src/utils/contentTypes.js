/**
 * Derive the "content type" badges a Context Pack should show in the UI.
 *
 * A pack can ship multiple representations of the same knowledge:
 *
 *   - **Text**   — always. Covers both the Markdown ``body`` and the
 *                  JSON ``structured_content`` (they're both
 *                  human-readable text payloads from the UI's point
 *                  of view). This is the default and is shown even
 *                  when a pack is empty, so users see at least one tag.
 *   - **Graph**  — present when ``graph_data`` is non-empty. Reserved
 *                  for future graph-extraction flows.
 *   - **Vector** — present when ``vector_index_id`` is set. Indicates
 *                  the pack has an embedding in an external store.
 *
 * The function is deliberately forgiving: unknown / null / legacy
 * packs still return ``['Text']`` so the Zoo UI always has at least
 * one chip to render.
 *
 * Pure / side-effect free so we can unit-test it without mounting Vue.
 *
 * @param {object|null|undefined} pack A Context Pack DTO as returned by
 *   the backend list/get endpoints (camelCase or snake_case keys OK).
 * @returns {string[]} Ordered list of unique tags, always with
 *   'Text' first.
 */
export function contentTypesForPack(pack) {
  const tags = ['Text']
  if (!pack || typeof pack !== 'object') return tags

  // graph_data can be a JSON object/array or a stringified JSON — we
  // treat any non-empty value as "has graph". We don't inspect the
  // schema; that's the graph service's job.
  const graph = pack.graph_data ?? pack.graphData
  if (hasContent(graph)) tags.push('Graph')

  const vectorId = pack.vector_index_id ?? pack.vectorIndexId
  if (typeof vectorId === 'string' && vectorId.trim()) tags.push('Vector')

  return tags
}

function hasContent(value) {
  if (value == null) return false
  if (typeof value === 'string') return value.trim().length > 0
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value).length > 0
  return false
}

/**
 * Readable label for a pack's ``source_type`` discriminator. Falls
 * back to 'Project' for NULL / legacy rows (the backend's documented
 * default).
 */
export function sourceTypeLabel(sourceType) {
  switch ((sourceType || '').toLowerCase()) {
    case 'project':
      return 'Project'
    case 'conversation':
      return 'Conversation'
    case 'message':
      return 'Message'
    case 'note':
      return 'Note'
    case 'attachment':
      return 'Attachment'
    case 'mixed':
      return 'Mixed'
    default:
      return 'Project'
  }
}

/**
 * Tailwind-ish chip variant for a given source_type. Falls back to the
 * neutral chip (no variant). The zoo uses these for color-coding.
 */
export function sourceTypeChipVariant(sourceType) {
  switch ((sourceType || '').toLowerCase()) {
    case 'project':
      return 'primary'
    case 'conversation':
      return 'success'
    case 'mixed':
      return 'warning'
    case 'note':
    case 'attachment':
    case 'message':
    default:
      return ''
  }
}

export default {
  contentTypesForPack,
  sourceTypeLabel,
  sourceTypeChipVariant
}
