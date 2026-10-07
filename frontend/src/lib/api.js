// SPDX-License-Identifier: AGPL-3.0-or-later
// Client HTTP minimal pour l'API Python (même origine ; proxy Vite en développement).
export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function request(method, path, body) {
  const options = { method, headers: {} }
  if (body instanceof FormData) {
    options.body = body
  } else if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(body)
  }
  let res
  try {
    res = await fetch(path, options)
  } catch {
    throw new ApiError('Serveur Caffein injoignable. Est-il bien lancé ?', 0)
  }
  if (res.status === 401 && !path.startsWith('/api/auth/') && !path.startsWith('/api/setup')) {
    // session expirée ou révoquée : l'AuthContext renvoie vers la page de connexion
    window.dispatchEvent(new CustomEvent('caffein:unauthorized'))
  }
  if (!res.ok) {
    let detail = ''
    try {
      const data = await res.json()
      detail = typeof data.detail === 'string' ? data.detail : data.detail?.[0]?.msg
    } catch {
      /* corps non JSON */
    }
    throw new ApiError(detail || `Erreur ${res.status}`, res.status)
  }
  return res.status === 204 ? null : res.json()
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body = {}) => request('POST', path, body),
  put: (path, body) => request('PUT', path, body),
  del: (path) => request('DELETE', path),
}
