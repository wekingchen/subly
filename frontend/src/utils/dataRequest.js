import { ref } from 'vue'

export function createRequestGuard() {
  let requestId = 0

  return {
    begin() {
      requestId += 1
      return requestId
    },
    isCurrent(id) {
      return id === requestId
    },
    invalidate() {
      requestId += 1
    }
  }
}

export function useDataRequest({ initialData, isEmpty = (value) => !value?.length } = {}) {
  const data = ref(initialData)
  const initialLoading = ref(false)
  const refreshing = ref(false)
  const error = ref(null)
  const stale = ref(false)
  const hasLoaded = ref(false)
  const guard = createRequestGuard()

  async function run(loader) {
    const requestId = guard.begin()
    const isInitial = !hasLoaded.value
    if (isInitial) initialLoading.value = true
    else refreshing.value = true
    error.value = null

    try {
      const value = await loader()
      if (!guard.isCurrent(requestId)) return { applied: false, value }
      data.value = value
      hasLoaded.value = true
      stale.value = false
      return { applied: true, value }
    } catch (requestError) {
      if (!guard.isCurrent(requestId)) return { applied: false, error: requestError }
      if (hasLoaded.value) stale.value = true
      else error.value = requestError
      return { applied: true, error: requestError }
    } finally {
      if (guard.isCurrent(requestId)) {
        initialLoading.value = false
        refreshing.value = false
      }
    }
  }

  function state() {
    if (initialLoading.value) return 'loading'
    if (error.value && !hasLoaded.value) return 'error'
    if (stale.value) return 'stale'
    if (refreshing.value) return 'refreshing'
    if (hasLoaded.value && isEmpty(data.value)) return 'empty'
    return 'ready'
  }

  return {
    data,
    initialLoading,
    refreshing,
    error,
    stale,
    hasLoaded,
    run,
    state,
    invalidate: guard.invalidate
  }
}
