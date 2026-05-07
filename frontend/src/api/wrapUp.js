import apiClient from './client'

// Wrap-up calls hit the LLM, so the default 15s client timeout is
// nowhere near enough. Give each call the same 120s ceiling the chat
// endpoints already use.
const WRAP_UP_TIMEOUT = 120_000

/**
 * Shape of a wrap-up request body. All fields optional.
 *
 *   title: string            // custom Context Pack title
 *   goal: string             // user's wrap-up goal (e.g. "整理本次技术方案讨论")
 *   conversationIds: int[]   // project-level only; omit = use all convos
 *   options: {
 *     includeRawReferences: boolean    // persist per-message source rows
 *     maxSummaryLength: number         // target chars for summary
 *   }
 */

export const wrapUpApi = {
  /**
   * Wrap up a single conversation into a Context Pack.
   * POST /api/conversations/:conversationId/wrap-up
   */
  forConversation(conversationId, payload = {}) {
    return apiClient
      .post(`/api/conversations/${conversationId}/wrap-up`, payload, {
        timeout: WRAP_UP_TIMEOUT
      })
      .then((r) => r.data)
  },

  /**
   * Wrap up a project (or a subset of its conversations) into a Context Pack.
   * POST /api/projects/:projectId/wrap-up
   */
  forProject(projectId, payload = {}) {
    return apiClient
      .post(`/api/projects/${projectId}/wrap-up`, payload, {
        timeout: WRAP_UP_TIMEOUT
      })
      .then((r) => r.data)
  },

  /**
   * Fetch the latest state of a wrap-up job. Used for progress polling.
   * GET /api/wrap-up-jobs/:jobId
   */
  getJob(jobId) {
    return apiClient
      .get(`/api/wrap-up-jobs/${jobId}`)
      .then((r) => r.data)
  }
}

// Canonical stage order used by the progress UI. Mirrors the backend
// JOB_STAGES_ORDER constant.
export const WRAP_UP_STAGES = [
  'preparing',
  'collecting_messages',
  'analyzing_content',
  'generating_summary',
  'creating_context_pack',
  'completed'
]

export const WRAP_UP_STAGE_LABELS = {
  preparing: 'Preparing',
  collecting_messages: 'Collecting messages',
  analyzing_content: 'Analyzing content',
  generating_summary: 'Generating summary',
  creating_context_pack: 'Creating Context Pack',
  completed: 'Completed',
  failed: 'Failed'
}

export default wrapUpApi
