<template>
  <div v-if="target && !isDesktopActionMode" class="action-mask" @click="emit('close')">
    <div
      ref="actionSheetRef"
      class="action-sheet"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      tabindex="-1"
      @click.stop
    >
      <ActionMenuContent
        :target="target"
        :title-id="titleId"
        :plan-text="planText"
        :show-move="showMove"
        :show-renew="showRenew"
        @close="emit('close')"
        @move="emit('move', $event)"
        @edit="emit('edit')"
        @renew="emit('renew')"
        @delete="emit('delete')"
      />
    </div>
  </div>

  <Teleport to="body">
    <div v-if="target && isDesktopActionMode" class="action-popover-backdrop" @click="emit('close')"></div>
    <div
      v-if="target && isDesktopActionMode"
      ref="actionPopoverRef"
      class="action-popover"
      role="dialog"
      aria-modal="false"
      :aria-labelledby="titleId"
      :style="actionPopoverStyle"
      tabindex="-1"
      @click.stop
    >
      <ActionMenuContent
        :target="target"
        :title-id="titleId"
        :plan-text="planText"
        :show-move="showMove"
        :show-renew="showRenew"
        @close="emit('close')"
        @move="emit('move', $event)"
        @edit="emit('edit')"
        @renew="emit('renew')"
        @delete="emit('delete')"
      />
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import ActionMenuContent from './ActionMenuContent.vue'
import { useBreakpoint } from '../../composables/useBreakpoint'
import { useDialogFocus } from '../../composables/useDialogFocus'

const props = defineProps({
  target: { type: Object, default: null },
  anchor: { type: Object, default: null },
  showMove: { type: Boolean, default: false }
})

const emit = defineEmits(['close', 'move', 'edit', 'renew', 'delete', 'mobile-lock-change'])

const actionSheetRef = ref(null)
const actionPopoverRef = ref(null)
// 始终指向当前活跃容器（sheet 或 popover），供 useDialogFocus 做 Tab 环绕。
const dialogRef = ref(null)
const isDesktopActionMode = useBreakpoint('(min-width: 721px)')

const DASH = '—'
const ACTION_EDGE = 12
const ACTION_GAP = 8
const ACTION_MIN_H = 80

const titleId = computed(() => props.target?.id != null ? `sub-action-title-${props.target.id}` : 'sub-action-title')
const planText = computed(() => textOrDash(props.target?.plan))
const showRenew = computed(() => props.target?.billing_type === 'recurring')
const mobileActionOpen = computed(() => !!props.target && !isDesktopActionMode.value)
const actionOpen = computed(() => !!props.target)

const actionPopoverStyle = computed(() => {
  const a = props.anchor
  if (!a || typeof window === 'undefined') return {}
  const vw = window.innerWidth
  const vh = window.innerHeight
  const width = Math.min(300, vw - ACTION_EDGE * 2)
  const maxLeft = Math.max(ACTION_EDGE, vw - width - ACTION_EDGE)
  const left = clamp(a.right - width, ACTION_EDGE, maxLeft)
  const below = vh - a.bottom - ACTION_GAP - ACTION_EDGE
  const above = a.top - ACTION_GAP - ACTION_EDGE
  if (below < 220 && above > below) {
    const bottom = clamp(vh - a.top + ACTION_GAP, ACTION_EDGE, Math.max(ACTION_EDGE, vh - ACTION_EDGE - ACTION_MIN_H))
    return {
      left: `${left}px`,
      bottom: `${bottom}px`,
      '--action-popover-max-h': `${Math.max(ACTION_MIN_H, vh - bottom - ACTION_EDGE)}px`
    }
  }
  const top = clamp(a.bottom + ACTION_GAP, ACTION_EDGE, Math.max(ACTION_EDGE, vh - ACTION_EDGE - ACTION_MIN_H))
  return {
    left: `${left}px`,
    top: `${top}px`,
    '--action-popover-max-h': `${Math.max(ACTION_MIN_H, vh - top - ACTION_EDGE)}px`
  }
})

function textOrDash(v) {
  return (v === null || v === undefined || v === '') ? DASH : v
}

function clamp(n, min, max) {
  return Math.min(Math.max(n, min), max)
}

// 把 dialogRef 同步到当前活跃容器，并聚焦它（处理打开与断点切换重聚焦）。
// 初始聚焦由本层显式控制，避免与 composable 的 enter nextTick 时序耦合；
// composable 只负责 Escape / Tab 环绕 / 栈管理。
function syncActiveDialog() {
  if (!props.target) {
    dialogRef.value = null
    return
  }
  nextTick(() => {
    const el = isDesktopActionMode.value ? actionPopoverRef.value : actionSheetRef.value
    dialogRef.value = el
    el?.focus?.()
  })
}

watch(mobileActionOpen, (open) => {
  emit('mobile-lock-change', open)
}, { immediate: true })

watch([() => props.target, isDesktopActionMode], syncActiveDialog, { immediate: true })

useDialogFocus({
  open: actionOpen,
  dialogRef,
  onClose: () => emit('close'),
  restoreFocus: false,
  trap: true
})

onBeforeUnmount(() => {
  emit('mobile-lock-change', false)
})
</script>

<style scoped>
.action-mask { position: fixed; inset: 0; z-index: 70; display: flex; align-items: flex-end; justify-content: center;
  padding: 14px; background: rgba(2, 6, 23, .54); backdrop-filter: blur(8px); }
.action-sheet { width: min(430px, 100%); border: 1px solid color-mix(in srgb, var(--border) 76%, transparent); border-radius: 24px;
  padding: 10px; background: linear-gradient(180deg, color-mix(in srgb, var(--surface) 94%, var(--signal-cyan)), var(--surface));
  box-shadow: 0 22px 70px rgba(0, 0, 0, .34); }
.action-popover { position: fixed; z-index: 80; width: 300px; max-width: calc(100vw - 24px);
  max-height: var(--action-popover-max-h, 70vh); overflow: auto; overscroll-behavior: contain;
  border: 1px solid color-mix(in srgb, var(--border) 76%, transparent); border-radius: 18px; padding: 8px;
  background: linear-gradient(180deg, color-mix(in srgb, var(--surface) 94%, var(--signal-cyan)), var(--surface));
  box-shadow: 0 18px 50px rgba(0, 0, 0, .22); }
.action-popover-backdrop { position: fixed; inset: 0; z-index: 79; background: transparent; }
</style>
