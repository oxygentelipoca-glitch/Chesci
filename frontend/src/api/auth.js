/**
 * 认证 API 封装 — 登录 / 注册 / 当前用户 + token 管理。
 */
import axios from "axios"

const API_BASE = import.meta.env.VITE_API_BASE || ""

const TOKEN_KEY = "rag_token"
const USER_KEY = "rag_user"

// ---- token 与用户信息的本地管理 ----

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ""
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export function getStoredUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || "null")
  } catch {
    return null
  }
}

export function setStoredUser(user) {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearStoredUser() {
  localStorage.removeItem(USER_KEY)
}

export function isLoggedIn() {
  return !!getToken()
}

export function logout() {
  clearToken()
  clearStoredUser()
}

// ---- API 调用 ----

/** POST /auth/login — 登录并保存 token。 */
export async function login(username, password) {
  const res = await axios.post(`${API_BASE}/auth/login`, { username, password })
  const d = res.data.data
  setToken(d.token)
  setStoredUser({ username: d.user, user_id: d.user_id })
  return d
}

/** POST /auth/register — 注册并保存 token。 */
export async function register(username, password) {
  const res = await axios.post(`${API_BASE}/auth/register`, { username, password })
  const d = res.data.data
  setToken(d.token)
  setStoredUser({ username: d.user, user_id: d.user_id })
  return d
}

/** GET /auth/me — 获取当前用户信息（校验 token 有效性）。 */
export async function getMe() {
  const res = await axios.get(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  return res.data.data
}
