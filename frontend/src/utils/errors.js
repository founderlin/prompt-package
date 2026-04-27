export function describeApiError(err, fallback = 'Something went wrong.') {
  if (!err) return fallback
  const data = err.response?.data
  if (data?.message) return data.message
  if (err.response) return `Request failed (${err.response.status}).`
  if (err.request) return 'Could not reach the server. Is the backend running?'
  return err.message || fallback
}
