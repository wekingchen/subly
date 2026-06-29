<template>
  <router-view />
</template>

<script setup>
import { onMounted } from 'vue'
import api from './api'
import { useAuth } from './stores/auth'

const auth = useAuth()
onMounted(() => {
  if (auth.isLoggedIn) {
    auth.fetchMe().catch(() => {})
    // 打开网页时自动查询当日汇率（后端仅在过期时才联网刷新）
    api.post('/api/currencies/rates/auto-refresh').catch(() => {})
  }
})
</script>
