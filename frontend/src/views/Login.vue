<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import ReactionScheme from '../components/ReactionScheme.vue'
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
  <main class="login-root">
    <section class="folio">
      <div class="brand"><img src="/favicon.svg" alt="" />ChemFinder</div>
      <div class="folio-body"><h1>化学合成路线<br />分析工作台</h1><ReactionScheme /></div>
      <span class="school">兰州交通大学</span>
    </section>
    <section class="login-form">
      <h2>{{ mode === 'login' ? '登录工作台' : '创建账号' }}</h2>
      <div class="lc-tabs"><button v-for="[value,label] in [['login','登录'],['register','注册']]" :key="value" :aria-pressed="mode === value" type="button" @click="switchMode(value)">{{ label }}</button></div>
      <form @submit.prevent="submit">
        <label>用户名<input v-model="username" placeholder="用户名" autocomplete="username" required /></label>
        <label>密码<input v-model="password" type="password" placeholder="密码（至少 4 位）" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" required /></label>
        <p v-if="errorMsg" role="alert" class="lc-error">{{ errorMsg }}</p>
        <button class="submit" type="submit" :disabled="loading">{{ loading ? '请稍候…' : (mode === 'login' ? '登录' : '注册') }}</button>
      </form>
      <p class="lc-hint">演示账号 <b>demo</b>　密码 <b>demo123</b></p>
    </section>
  </main>
</template>
<style scoped>
.login-root { min-height:100svh; display:grid; grid-template-columns:minmax(0,1.1fr) minmax(0,1fr); background:#fff }
.folio { background:#143d43; color:#e6f6ed; display:flex; flex-direction:column; justify-content:space-between; gap:32px; padding:clamp(30px,6vw,100px) }
.brand { color:white }
.folio h1 { font-size:clamp(36px,4.4vw,68px); line-height:1.2; letter-spacing:-.05em; margin-bottom:4vw }
.folio .scheme { max-width:550px }
.school,.lc-hint { font-size:13px }
.school { color:#b5d6cd }
.login-form { align-self:center; justify-self:center; width:min(74%,360px); padding:40px 0 }
.login-form h2 { font-size:30px; margin-bottom:20px }
.lc-tabs { display:flex; border-bottom:1px solid var(--border); margin-bottom:22px }
button { cursor:pointer }
.lc-tabs button { font-size:15px; padding:8px 18px; border:0; border-bottom:3px solid transparent; background:none; color:var(--text-light) }
.lc-tabs button[aria-pressed=true] { border-bottom-color:var(--primary); color:var(--primary); font-weight:700 }
form,label { display:grid; gap:7px }
form { gap:16px }
input { border:1px solid var(--border); border-radius:6px; padding:12px; font-size:15px }
.submit { color:white; background:var(--primary); border:0; border-radius:6px; min-height:44px; font-weight:650; font-size:15px }
.submit:disabled { opacity:.65 }
.lc-hint { color:var(--text-light); margin-top:18px }
.lc-error { color:var(--danger) }
@media(max-width:700px){.login-root { grid-template-columns:1fr; align-content:start }.folio { padding:20px 6vw; gap:14px }.folio-body { display:flex; align-items:center; gap:12px }.folio h1 { font-size:23px; flex-shrink:0; margin:0 }.folio .scheme { width:58%; max-width:240px }.school { display:none }.login-form { width:min(88%,380px) }}
</style>
