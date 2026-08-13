;(function () {
  const themes = {
    light: '#f6f8fc',
    dark: '#07111f',
    ocean: '#ecfeff',
    forest: '#f0fdf4',
    purple: '#faf5ff'
  }
  let theme = 'light'
  try {
    const saved = localStorage.getItem('subly_theme')
    if (Object.prototype.hasOwnProperty.call(themes, saved)) theme = saved
  } catch {
    // 存储不可用时使用安全默认主题。
  }
  document.documentElement.dataset.theme = theme
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', themes[theme])
})()
