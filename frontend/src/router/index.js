import { createRouter, createWebHistory } from 'vue-router'
import { isLoggedIn } from '../api/auth.js'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
  { path: '/route-planning', name: 'RoutePlanning', component: () => import('../views/RoutePlanning.vue') },
  { path: '/knowledge-graph', name: 'KnowledgeGraph', component: () => import('../views/KnowledgeGraph.vue') },
  { path: '/literature', name: 'Literature', component: () => import('../views/Literature.vue') },
  { path: '/experiment', name: 'Experiment', component: () => import('../views/Experiment.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 全局守卫：未登录跳转登录页（/login 公开页除外）
router.beforeEach((to) => {
  if (to.meta.public) return true
  if (!isLoggedIn()) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router
