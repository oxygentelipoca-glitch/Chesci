<script setup>
import { useRouter } from 'vue-router'
import { getStoredUser, logout } from '../api/auth.js'

const router = useRouter()
const username = getStoredUser()?.username || '游客'
const navItems = [
  ['/', '工作台'], ['/route-planning', '路线规划'], ['/knowledge-graph', '知识图谱'],
  ['/literature', '文献检索'], ['/experiment', '实验助手'],
]
function handleLogout() {
  logout()
  router.push('/login')
}
</script>
<template>
  <div class="app-shell">
    <header class="shell-bar">
      <div class="shell-inner">
        <RouterLink class="brand" to="/" aria-label="ChemFinder 首页"><img src="/favicon.svg" alt="" />ChemFinder</RouterLink>
        <nav aria-label="研究工作区"><RouterLink v-for="[path, label] in navItems" :key="path" :to="path">{{ label }}</RouterLink></nav>
        <div class="account"><span>{{ username }}</span><button @click="handleLogout">退出</button></div>
      </div>
    </header>
    <main class="workspace"><slot /></main>
  </div>
</template>
<style scoped>
.shell-bar { background:white; border-bottom:1px solid var(--border) }
.shell-inner,.workspace { width:min(1200px,92%); margin:auto }
.shell-inner { display:flex; align-items:center; gap:clamp(20px,4vw,68px); min-height:70px }
nav { display:flex; gap:clamp(14px,2vw,32px); align-self:stretch }
nav a { display:grid; align-items:center; color:var(--text-light); font-weight:600; padding:0 2px; border-bottom:3px solid transparent; border-top:3px solid transparent }
nav a.router-link-exact-active { color:var(--primary); border-bottom-color:var(--primary) }
.account { margin-left:auto; display:flex; align-items:center; gap:12px; min-width:0; color:var(--text-light) }
.account span { max-width:12ch; white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
.account button { cursor:pointer; border:1px solid var(--border); border-radius:6px; padding:4px 10px; background:white; color:var(--text) }
.workspace { padding:clamp(20px,3.5vw,48px) 0 60px; }
@media(max-width:800px){
  .shell-inner { flex-wrap:wrap; gap:0; padding-top:12px }
  nav { order:3; width:100%; justify-content:space-between; gap:6px; padding-top:6px }
  nav a { min-height:43px; font-size:13px }
}
</style>
