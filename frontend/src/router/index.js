import { createRouter, createWebHistory } from 'vue-router'
import AppShell from '@/layouts/AppShell.vue'
import { useAuth } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/auth/LoginView.vue'),
      meta: { title: 'Sign in', public: true, authOnly: true }
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('@/views/auth/RegisterView.vue'),
      meta: { title: 'Create account', public: true, authOnly: true }
    },
    {
      path: '/',
      component: AppShell,
      redirect: '/dashboard',
      children: [
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { title: 'Dashboard', subtitle: 'Overview of your AI project memory' }
        },
        {
          path: 'projects',
          name: 'projects',
          component: () => import('@/views/ProjectsView.vue'),
          meta: { title: 'Projects' }
        },
        {
          path: 'projects/:id(\\d+)',
          name: 'project-detail',
          component: () => import('@/views/ProjectDetailView.vue'),
          props: true,
          meta: { title: 'Project' }
        },
        {
          path: 'projects/:id(\\d+)/chat/:cid(\\d+)?',
          name: 'project-chat',
          component: () => import('@/views/ProjectChatView.vue'),
          props: true,
          meta: { title: 'Chat' }
        },
        {
          path: 'projects/:id(\\d+)/context-packs/:packId(\\d+)',
          name: 'project-context-pack',
          component: () => import('@/views/ContextPackView.vue'),
          props: true,
          meta: { title: 'Context Pack' }
        },
        {
          path: 'search',
          name: 'search',
          component: () => import('@/views/SearchView.vue'),
          meta: { title: 'Search' }
        },
        {
          path: 'context-packs',
          name: 'context-packs',
          component: () => import('@/views/ContextPacksView.vue'),
          meta: { title: 'Context Packs' }
        },
        {
          path: 'context-zoo',
          name: 'context-zoo',
          component: () => import('@/views/ContextZooView.vue'),
          meta: { title: 'Context Zoo' }
        },
        {
          path: 'context-zoo/:contextPackId(\\d+)',
          name: 'context-zoo-detail',
          component: () => import('@/views/ContextZooDetailView.vue'),
          props: true,
          meta: { title: 'Context Pack' }
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/SettingsView.vue'),
          meta: { title: 'Settings' }
        },
        {
          path: 'privacy',
          name: 'privacy',
          component: () => import('@/views/PrivacyView.vue'),
          meta: { title: 'Privacy', public: true }
        },
        {
          path: ':pathMatch(.*)*',
          name: 'not-found',
          component: () => import('@/views/NotFoundView.vue'),
          meta: { title: 'Not found', public: true }
        }
      ]
    }
  ],
  scrollBehavior() {
    return { top: 0 }
  }
})

router.beforeEach(async (to) => {
  const auth = useAuth()
  if (!auth.ready.value) {
    await auth.init()
  }
  const isPublic = to.meta?.public === true
  const isAuthOnly = to.meta?.authOnly === true

  if (isAuthOnly && auth.isAuthenticated.value) {
    return { name: 'dashboard' }
  }
  if (!isPublic && !auth.isAuthenticated.value) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  return true
})

const APP_NAME = 'Prompt Package'

router.afterEach((to) => {
  const pageTitle = to.meta?.title
  document.title = pageTitle ? `${pageTitle} · ${APP_NAME}` : APP_NAME
})

export default router
