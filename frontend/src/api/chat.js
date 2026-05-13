import apiClient, { apiBaseURL } from './client'

// SSE wire format helper. One record looks like:
//
//   event: delta
//   data: "fragment"
//
// We accept either a single ``data:`` line or several joined by
// newlines. Returns ``{ event, data }`` or ``null`` when the record
// can't be parsed (e.g. comment-only lines starting with ``:``).
function parseSseRecord(raw) {
  if (!raw) return null
  let event = 'message'
  const dataLines = []
  for (const line of raw.split('\n')) {
    if (!line || line.startsWith(':')) continue
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart())
    }
  }
  if (!dataLines.length) return null
  const joined = dataLines.join('\n')
  let data
  try {
    data = JSON.parse(joined)
  } catch (_e) {
    data = joined
  }
  return { event, data }
}

export const chatApi = {
  listAllConversations({ limit } = {}) {
    const params = {}
    if (limit != null) params.limit = limit
    return apiClient
      .get('/api/conversations', { params })
      .then((r) => r.data)
  },
  listConversations(projectId) {
    return apiClient
      .get(`/api/projects/${projectId}/conversations`)
      .then((r) => r.data)
  },
  createConversation(projectId, payload = {}) {
    return apiClient
      .post(`/api/projects/${projectId}/conversations`, payload)
      .then((r) => r.data)
  },
  getConversation(conversationId) {
    return apiClient
      .get(`/api/conversations/${conversationId}`)
      .then((r) => r.data)
  },
  updateConversation(conversationId, patch) {
    return apiClient
      .patch(`/api/conversations/${conversationId}`, patch)
      .then((r) => r.data)
  },
  deleteConversation(conversationId) {
    return apiClient
      .delete(`/api/conversations/${conversationId}`)
      .then((r) => r.data)
  },
  deleteMessage(conversationId, messageId) {
    // Server cascades: the message + everything after it are removed.
    return apiClient
      .delete(
        `/api/conversations/${conversationId}/messages/${messageId}`
      )
      .then((r) => r.data)
  },
  listMessages(conversationId) {
    return apiClient
      .get(`/api/conversations/${conversationId}/messages`)
      .then((r) => r.data)
  },
  sendMessage(
    conversationId,
    { content, model, provider, attachmentIds, contextItems, signal } = {}
  ) {
    const body = { content, model }
    if (provider) body.provider = provider
    if (Array.isArray(attachmentIds) && attachmentIds.length) {
      body.attachment_ids = attachmentIds
    }
    if (Array.isArray(contextItems) && contextItems.length) {
      // Frontend sends camelCase; backend accepts both shapes (see
      // conversations.create_message). Pick camelCase for consistency
      // with the rest of the chat payload.
      body.contextItems = contextItems
    }
    const config = {}
    if (signal) config.signal = signal
    // Chat completions can take a while on big prompts; avoid axios's
    // default 15s timeout cutting us off mid-flight.
    config.timeout = 120_000
    return apiClient
      .post(
        `/api/conversations/${conversationId}/messages`,
        body,
        config
      )
      .then((r) => r.data)
  },
  /**
   * Streaming counterpart of :func:`sendMessage`. Returns an async
   * iterable that yields ``{ event, data }`` records as the server's
   * Server-Sent Events arrive. Event types come straight from the
   * backend route:
   *
   *   - ``user_message`` (once, immediately)
   *   - ``delta`` (zero or more, payload is the text fragment string)
   *   - ``assistant_message`` (once, terminal)
   *   - ``conversation`` (once, terminal)
   *   - ``error`` (terminal — caller should surface ``data.message``)
   *
   * Axios doesn't support SSE, so we go through ``fetch`` directly.
   * Auth is added via the same ``Authorization: Bearer …`` header
   * the axios client uses (read off the in-memory auth store).
   */
  async *sendMessageStream(
    conversationId,
    {
      content,
      model,
      provider,
      attachmentIds,
      contextItems,
      signal,
      authToken
    } = {}
  ) {
    const body = { content, model }
    if (provider) body.provider = provider
    if (Array.isArray(attachmentIds) && attachmentIds.length) {
      body.attachment_ids = attachmentIds
    }
    if (Array.isArray(contextItems) && contextItems.length) {
      body.contextItems = contextItems
    }

    const headers = {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream'
    }
    if (authToken) headers.Authorization = `Bearer ${authToken}`

    // Prepend the same base URL axios uses. In dev that's
    // ``http://127.0.0.1:5001`` (vite serves on :5173 and has no
    // proxy); in prod it's empty so we issue a same-origin request
    // that nginx forwards to gunicorn.
    const url = `${apiBaseURL}/api/conversations/${conversationId}/messages/stream`
    const resp = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
      // Browser default; mentioned explicitly so it's obvious we
      // expect cookies/session headers to flow.
      credentials: 'same-origin'
    })

    if (!resp.ok || !resp.body) {
      // Try to surface the server's JSON error; fall back to status.
      let message = `Stream failed (${resp.status}).`
      try {
        const data = await resp.json()
        if (data?.message) message = data.message
      } catch (_e) {
        /* ignore */
      }
      const err = new Error(message)
      err.status = resp.status
      throw err
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        // SSE records are separated by a blank line (``\n\n``).
        let sep
        // eslint-disable-next-line no-cond-assign
        while ((sep = buffer.indexOf('\n\n')) !== -1) {
          const raw = buffer.slice(0, sep)
          buffer = buffer.slice(sep + 2)
          const parsed = parseSseRecord(raw)
          if (parsed) yield parsed
        }
      }
      // Flush any trailing record (servers occasionally omit the
      // final ``\n\n`` when closing — we still want the event).
      const tail = buffer.trim()
      if (tail) {
        const parsed = parseSseRecord(tail)
        if (parsed) yield parsed
      }
    } finally {
      try {
        reader.releaseLock()
      } catch (_e) {
        /* ignore */
      }
    }
  },

  summarizeConversation(conversationId, { model } = {}) {
    const body = {}
    if (model) body.model = model
    return apiClient
      .post(`/api/conversations/${conversationId}/summarize`, body)
      .then((r) => r.data)
  },
  retryAssistant(
    conversationId,
    { model, provider, messageId, content, attachmentIds, signal } = {}
  ) {
    const body = {}
    if (model) body.model = model
    if (provider) body.provider = provider
    if (messageId != null) body.message_id = messageId
    if (content != null) body.content = content
    if (attachmentIds !== undefined) {
      body.attachment_ids = Array.isArray(attachmentIds)
        ? attachmentIds
        : []
    }
    const config = { timeout: 120_000 }
    if (signal) config.signal = signal
    return apiClient
      .post(
        `/api/conversations/${conversationId}/regenerate`,
        body,
        config
      )
      .then((r) => r.data)
  },

  /**
   * Streaming retry. Same SSE event shape as :func:`sendMessageStream`,
   * but it never emits ``user_message`` (the user row is already
   * on-screen for retry). The route slices the conversation server-
   * side before streaming the new assistant reply.
   */
  async *retryAssistantStream(
    conversationId,
    {
      model,
      provider,
      messageId,
      content,
      attachmentIds,
      signal,
      authToken
    } = {}
  ) {
    const body = {}
    if (model) body.model = model
    if (provider) body.provider = provider
    if (messageId != null) body.message_id = messageId
    if (content != null) body.content = content
    if (attachmentIds !== undefined) {
      body.attachment_ids = Array.isArray(attachmentIds)
        ? attachmentIds
        : []
    }

    const headers = {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream'
    }
    if (authToken) headers.Authorization = `Bearer ${authToken}`

    const url = `${apiBaseURL}/api/conversations/${conversationId}/regenerate/stream`
    const resp = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
      credentials: 'same-origin'
    })

    if (!resp.ok || !resp.body) {
      let message = `Stream failed (${resp.status}).`
      try {
        const data = await resp.json()
        if (data?.message) message = data.message
      } catch (_e) {
        /* ignore */
      }
      const err = new Error(message)
      err.status = resp.status
      throw err
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let sep
        // eslint-disable-next-line no-cond-assign
        while ((sep = buffer.indexOf('\n\n')) !== -1) {
          const raw = buffer.slice(0, sep)
          buffer = buffer.slice(sep + 2)
          const parsed = parseSseRecord(raw)
          if (parsed) yield parsed
        }
      }
      const tail = buffer.trim()
      if (tail) {
        const parsed = parseSseRecord(tail)
        if (parsed) yield parsed
      }
    } finally {
      try {
        reader.releaseLock()
      } catch (_e) {
        /* ignore */
      }
    }
  }
}

export default chatApi
