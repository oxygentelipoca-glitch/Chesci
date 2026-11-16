<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { getStoredUser, logout } from '../api/auth.js'

const router = useRouter()
const route = useRoute()

const navItems = [
  { path: '/', label: '首页', icon: '📊' },
  { path: '/route-planning', label: '路线规划', icon: '🧬' },
  { path: '/knowledge-graph', label: '知识图谱', icon: '🔗' },
  { path: '/literature', label: '文献检索', icon: '📚' },
  { path: '/experiment', label: '实验助手', icon: '⚗️' },
]

const username = ref(getStoredUser()?.username || '游客')

function isActive(path) { return route.path === path }
function navigate(path) { router.push(path) }

function handleLogout() {
  logout()
  router.push('/login')
}
</script>

<template>
  <div class="app-shell">
    <!-- 顶栏 -->
    <header class="topbar">
      <div class="tb-brand">
        <span class="tb-logo">⬡</span>
        <span class="tb-name">ChemGraph AI</span>
        <span class="tb-sub">智能化学研发平台</span>
      </div>
      <div class="tb-right">
        <span class="tb-user">👤 {{ username }}</span>
        <button class="tb-logout" @click="handleLogout">退出</button>
      </div>
    </header>

    <div class="app-body">
      <!-- 侧栏 -->
      <nav class="sidebar">
        <div
          v-for="item in navItems" :key="item.path"
          class="nav-item" :class="{ active: isActive(item.path) }"
          @click="navigate(item.path)"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span class="nav-label">{{ item.label }}</span>
        </div>
      </nav>

      <!-- 工作区 -->
      <main class="workspace">
        <slot />
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell { height: 100vh; display: flex; flex-direction: column; }

/* 顶栏 */
.topbar {
  height: 44px; display: flex; align-items: center; justify-content: space-between;
  padding: 0 20px; background: var(--primary); color: #fff; flex-shrink: 0;
  user-select: none;
}
.tb-brand { display: flex; align-items: center; gap: 8px; }
.tb-logo { font-size: 20px; }
.tb-name { font-weight: 700; font-size: 15px; letter-spacing: 0.5px; }
.tb-sub { font-size: 11px; opacity: 0.7; margin-left: 4px; }
.tb-right { display: flex; align-items: center; gap: 16px; font-size: 13px; opacity: 0.85; }
.tb-logout {
  background: rgba(255, 255, 255, 0.15);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 6px;
  padding: 4px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.12s;
}
.tb-logout:hover { background: rgba(255, 255, 255, 0.3); }

/* 主体 */
.app-body { display: flex; flex: 1; overflow: hidden; }

/* 侧栏 */
.sidebar {
  width: 180px; flex-shrink: 0; background: #FFF; border-right: 1px solid var(--border);
  padding: 12px 8px; display: flex; flex-direction: column; gap: 2px;
}
.nav-item {
  display: flex; align-items: center; gap: 10px; padding: 10px 14px;
  border-radius: var(--radius); cursor: pointer; font-size: 13px; color: var(--text);
  transition: all 0.12s; user-select: none;
}
.nav-item:hover { background: var(--primary-pale); }
.nav-item.active { background: var(--primary-pale); color: var(--primary); font-weight: 600; }
.nav-icon { font-size: 16px; width: 22px; text-align: center; }

/* 工作区 */
.workspace { flex: 1; overflow: auto; padding: 24px; background: var(--bg); }
</style>
