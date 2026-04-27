/**
 * Attachment API client.
 *
 * Uploads go up as multipart/form-data. We let axios pick the right
 * Content-Type boundary automatically (setting it to null to drop the
 * default application/json from the shared client config).
 *
 * Upload progress is forwarded via an optional onProgress(frac 0..1)
 * callback so the composer can render a per-file progress ring.
 */

import apiClient from './client'

const UPLOAD_TIMEOUT_MS = 120_000 // 2 minutes — a 10MB PDF on a slow link

export const attachmentsApi = {
  upload(conversationId, file, { onProgress } = {}) {
    const form = new FormData()
    form.append('file', file)
    return apiClient
      .post(
        `/api/conversations/${conversationId}/attachments`,
        form,
        {
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: UPLOAD_TIMEOUT_MS,
          onUploadProgress: (e) => {
            if (!onProgress || !e?.total) return
            try {
              onProgress(Math.max(0, Math.min(1, e.loaded / e.total)))
            } catch (_err) {
              /* ignore listener errors */
            }
          }
        }
      )
      .then((r) => r.data)
  },

  list(conversationId) {
    return apiClient
      .get(`/api/conversations/${conversationId}/attachments`)
      .then((r) => r.data)
  },

  remove(conversationId, attachmentId) {
    return apiClient
      .delete(
        `/api/conversations/${conversationId}/attachments/${attachmentId}`
      )
      .then((r) => r.data)
  },

  /** Absolute URL to the authenticated download endpoint (for <img src>). */
  downloadUrl(conversationId, attachmentId) {
    const base =
      apiClient.defaults.baseURL ||
      import.meta.env.VITE_API_BASE_URL ||
      ''
    return `${base}/api/conversations/${conversationId}/attachments/${attachmentId}/download`
  }
}

export default attachmentsApi
