<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login, register } from '../api/auth.js'

const router = useRouter()
const mode = ref('login') // login | register
const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')

function switchMode(m) {
  mode.value = m
  errorMsg.value = ''
}

async function submit() {
  if (!username.value.trim() || !password.value) {
    errorMsg.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    if (mode.value === 'login') {
      await login(username.value.trim(), password.value)
    } else {
      await register(username.value.trim(), password.value)
    }
    router.push('/')
  } catch (e) {
    errorMsg.value = e.response?.data?.message || '操作失败，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-root">
    <div class="login-card">
      <div class="lc-brand">
        <span class="lc-logo">⬡</span>
        <h1>ChemGraph AI</h1>
        <p>智能化学研发平台</p>
      </div>

      <div class="lc-tabs">
        <button :class="{ active: mode === 'login' }" @click="switchMode('login')">登录</button>
        <button :class="{ active: mode === 'register' }" @click="switchMode('register')">注册</button>
      </div>

      <form @submit.prevent="submit">
        <input
          v-model="username"
          placeholder="用户名"
          autocomplete="username"
        />
        <input
          v-model="password"
          type="password"
          placeholder="密码（至少 4 位）"
          autocomplete="current-password"
        />
        <p v-if="errorMsg" class="lc-error">{{ errorMsg }}</p>
        <button type="submit" :disabled="loading">
          {{ loading ? '请稍候...' : (mode === 'login' ? '登 录' : '注 册') }}
        </button>
      </form>

      <p class="lc-hint">演示账号：demo / demo123</p>
    </div>
  </div>
</template>

<style scoped>
.login-root {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0d9488, #0f766e);
}

.login-card {
  width: 380px;
  background: #fff;
  border-radius: 16px;
  padding: 36px 32px 28px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
}

.lc-brand { text-align: center; margin-bottom: 24px; }
.lc-logo { font-size: 40px; }
.lc-brand h1 { font-size: 22px; font-weight: 700; color: #0d9488; margin: 6px 0 2px; }
.lc-brand p { font-size: 12px; color: #9ca3af; }

.lc-tabs { display: flex; background: #f3f4f6; border-radius: 10px; padding: 4px; margin-bottom: 20px; }
.lc-tabs button {
  flex: 1; padding: 8px; border: none; background: transparent;
  border-radius: 8px; font-size: 14px; font-weight: 600; color: #6b7280; cursor: pointer;
  transition: all 0.15s;
}
.lc-tabs button.active { background: #fff; color: #0d9488; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }

form { display: flex; flex-direction: column; gap: 12px; }
form input {
  padding: 12px 16px;
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  font-size: 14px;
  outline: none;
  transition: border 0.15s;
}
form input:focus { border-color: #0d9488; }
.lc-error { font-size: 12px; color: #991b1b; margin: 0; }
form button {
  padding: 12px;
  background: #0d9488;
  color: #fff;
  border: none;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
form button:hover { background: #0f766e; }
form button:disabled { opacity: 0.6; cursor: not-allowed; }

.lc-hint { text-align: center; font-size: 12px; color: #9ca3af; margin-top: 16px; }
</style>
