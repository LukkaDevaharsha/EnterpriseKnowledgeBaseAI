const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

function notifyExpiredToken(token, response) {
  if (token && response.status === 401) window.dispatchEvent(new Event('auth:expired'))
}

export async function apiRequest(path, { token, method = 'GET', body, headers = {}, signal } = {}) {
  const requestHeaders = new Headers(headers)
  if (token) requestHeaders.set('Authorization', `Bearer ${token}`)
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  if (body !== undefined && !isForm && !requestHeaders.has('Content-Type')) {
    requestHeaders.set('Content-Type', 'application/json')
  }

  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: requestHeaders,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (error.name === 'AbortError' || error.name === 'TimeoutError') {
      throw new ApiError('The request took too long. Please try again.', 0)
    }
    throw new ApiError('Unable to reach the server. Check that the backend is running and try again.', 0)
  }

  let payload = null
  const text = await response.text()
  if (text) {
    try { payload = JSON.parse(text) } catch { payload = null }
  }
  if (!response.ok) {
    notifyExpiredToken(token, response)
    const message = payload?.message || payload?.error || `Request failed (${response.status}).`
    throw new ApiError(message, response.status, payload)
  }
  return payload
}

export const authApi = {
  login: (credentials) => apiRequest('/api/auth/login', { method: 'POST', body: credentials }),
  register: (details) => apiRequest('/api/auth/register', { method: 'POST', body: details }),
  me: (token) => apiRequest('/api/auth/me', { token }),
  verify: (credentials) => apiRequest('/api/auth/verify', { method: 'POST', body: credentials }),
  resendVerification: (email) => apiRequest('/api/auth/resend-verification', { method: 'POST', body: { email } }),
}

export const documentsApi = {
  list: (token, page = 1, perPage = 100) => apiRequest(`/api/documents?page=${page}&per_page=${perPage}`, { token }),
  upload: (token, formData) => apiRequest('/api/documents', { token, method: 'POST', body: formData }),
  remove: (token, id) => apiRequest(`/api/documents/${id}`, { token, method: 'DELETE' }),
  download: async (token, id, filename) => {
    let response
    try {
      response = await fetch(`${API_BASE}/api/documents/${id}/download`, { headers: { Authorization: `Bearer ${token}` } })
    } catch {
      throw new ApiError('Unable to reach the server. Check that the backend is running and try again.', 0)
    }
    if (!response.ok) {
      notifyExpiredToken(token, response)
      let payload
      try { payload = await response.json() } catch { payload = null }
      throw new ApiError(payload?.message || `Download failed (${response.status}).`, response.status, payload)
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename || 'document'
    document.body.append(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  },
}

export const ragApi = {
  ask: (token, question, topK = 5, { documentId, signal } = {}) => apiRequest(
    documentId ? `/api/study/documents/${documentId}/ask` : '/api/ask',
    {
      token,
      method: 'POST',
      body: { question, top_k: topK },
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(120000)]) : AbortSignal.timeout(120000),
    },
  ),
}

async function authorizedBlob(token, path) {
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
  } catch {
    throw new ApiError('Unable to reach the server. Check that the backend is running and try again.', 0)
  }
  if (!response.ok) {
    notifyExpiredToken(token, response)
    let payload
    try { payload = await response.json() } catch { payload = null }
    throw new ApiError(payload?.message || `Request failed (${response.status}).`, response.status, payload)
  }
  return response.blob()
}

export const adminApi = {
  stats: (token) => apiRequest('/api/admin/stats', { token }),
  employees: (token, page = 1, perPage = 100) => apiRequest(`/api/admin/employees?page=${page}&per_page=${perPage}`, { token }),
  updateEmployee: (token, id, changes) => apiRequest(`/api/admin/employees/${id}`, { token, method: 'PATCH', body: changes }),
  documents: (token) => apiRequest('/api/admin/documents?per_page=100', { token }),
  uploadDocument: (token, formData) => apiRequest('/api/admin/documents', { token, method: 'POST', body: formData }),
  inspectDocument: (token, id) => apiRequest(`/api/admin/documents/${id}`, { token }),
  deleteDocument: (token, id) => apiRequest(`/api/admin/documents/${id}`, { token, method: 'DELETE' }),
  audit: (token) => apiRequest('/api/admin/audit?per_page=50', { token }),
}

export const studyApi = {
  documents: (token) => apiRequest('/api/study/documents', { token }),
  pages: (token, id) => apiRequest(`/api/study/documents/${id}/pages`, { token }),
  pdf: (token, id) => authorizedBlob(token, `/api/study/documents/${id}/download`),
  renderPage: (token, id, pageNumber, query, scale = 1.5) => {
    const params = new URLSearchParams({ scale: String(scale) })
    if (query) params.set('query', query)
    return authorizedBlob(token, `/api/study/documents/${id}/pages/${pageNumber}/render?${params}`)
  },
  ask: (token, id, question, topK = 5, signal) => ragApi.ask(token, question, topK, { documentId: id, signal }),
}
