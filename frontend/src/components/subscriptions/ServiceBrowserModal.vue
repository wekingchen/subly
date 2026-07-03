<template>
  <div class="modal-mask browser">
    <div
      ref="dialogRef"
      class="modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="service-browser-title"
      tabindex="-1"
    >
      <div class="browser-head">
        <h3 id="service-browser-title" class="browser-title">📚 {{ t('sub.browseTitle') }}</h3>
        <button type="button" class="btn ghost sm" @click="emit('close')">{{ t('common.close') }}</button>
      </div>

      <p class="muted browser-hint">{{ t('sub.pickHint') }}</p>
      <input
        id="service-browser-search"
        ref="searchRef"
        v-model="query"
        class="browser-search"
        name="service_browser_search"
        :placeholder="t('sub.searchPh')"
        :aria-label="t('sub.searchPh')"
      />

      <div v-for="g in groupedServices" :key="g.key" class="lib-group">
        <button
          type="button"
          class="lib-group-t browser-group-t"
          :aria-expanded="isGroupExpanded(g.key)"
          :aria-controls="groupPanelId(g.key)"
          @click="toggleGroup(g.key)"
        >
          <span aria-hidden="true">{{ isGroupExpanded(g.key) ? '▾' : '▸' }}</span>
          <span>{{ g.label }}</span>
          <span class="muted">({{ g.items.length }})</span>
        </button>
        <div v-if="isGroupExpanded(g.key)" :id="groupPanelId(g.key)" class="svc-grid">
          <button v-for="s in g.items" :key="s.slug" type="button" class="svc" @click="selectService(s)">
            <ServiceIcon :src="s.icon" :name="s.name" class="svc-ico" loading="lazy" decoding="async" />
            <span>{{ s.name }}</span>
          </button>
        </div>
      </div>

      <p v-if="!groupedServices.length" class="muted browser-empty">{{ t('reports.empty') }}</p>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ServiceIcon from '../ServiceIcon.vue'
import { useDialogFocus } from '../../composables/useDialogFocus'
import { groupServicesByCategory } from '../../utils/serviceLibrary'

const props = defineProps({
  services: { type: Array, default: () => [] }
})

const emit = defineEmits(['close', 'pick'])
const { t } = useI18n()

const query = ref('')
const dialogRef = ref(null)
const searchRef = ref(null)

// 浏览器由父级 v-if 控制挂载，挂载即打开；关闭后把焦点还给外层表单的“浏览服务”按钮。
useDialogFocus({
  open: () => true,
  dialogRef,
  initialFocus: searchRef,
  onClose: () => emit('close'),
  restoreFocus: true,
  trap: true
})
const openGroupKeys = ref(new Set())
const hasQuery = computed(() => query.value.trim().length > 0)
const groupedServices = computed(() => groupServicesByCategory(props.services, query.value))

function isGroupExpanded(key) {
  return hasQuery.value || openGroupKeys.value.has(key)
}

function toggleGroup(key) {
  const next = new Set(openGroupKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  openGroupKeys.value = next
}

function groupPanelId(key) {
  return `service-browser-group-${String(key).replace(/[^a-zA-Z0-9_-]/g, '-')}`
}

function selectService(service) {
  emit('pick', service)
}
</script>

<style scoped>
.browser .modal { width: 560px; }
.browser-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.browser-title { margin: 0; }
.browser-hint { font-size: 13px; margin-top: 0; }
.browser-search { margin-bottom: 12px; }
.lib-group { margin-bottom: 14px; }
.lib-group-t { font-size: 13px; font-weight: 600; color: var(--text-soft); margin-bottom: 8px; }
.browser-group-t { width: 100%; display: flex; align-items: center; gap: 6px; padding: 0; border: none; background: transparent; cursor: pointer; text-align: left; }
.svc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.svc { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid var(--border);
  border-radius: 10px; background: var(--surface); cursor: pointer; font-size: 13px; color: var(--text);
  text-align: left; transition: border-color .12s, background .12s; }
.svc:hover { border-color: var(--primary); background: var(--primary-soft); }
.svc-ico { width: 22px; height: 22px; border-radius: 5px; object-fit: contain; flex-shrink: 0; }
.svc span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.browser-empty { margin-bottom: 0; }
@media (max-width: 720px) {
  .browser-head { align-items: flex-start; }
  .browser-group-t { min-height: 44px; padding: 6px 0; }
  .svc { min-height: 44px; }
  .svc span { white-space: normal; line-height: 1.3; }
}
</style>
