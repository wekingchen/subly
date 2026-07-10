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
    // 路由守卫已完成会话恢复；打开网页时仅触发当日汇率自动刷新。
    api.post('/api/currencies/rates/auto-refresh').catch(() => {})
  }
})
</script>
