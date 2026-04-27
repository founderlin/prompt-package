/**
 * Usage metrics API client.
 *
 * Backend returns a gap-filled array of buckets so the chart can draw
 * a continuous line even on quiet days.
 */

import apiClient from './client'

export const usageApi = {
  summary({ granularity = 'day' } = {}) {
    return apiClient
      .get('/api/usage/summary', { params: { granularity } })
      .then((r) => r.data)
  }
}

export default usageApi
