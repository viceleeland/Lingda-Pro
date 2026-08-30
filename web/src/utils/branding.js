export const APP_BRAND_NAME = '灵答'
export const APP_COPYRIGHT = '© 灵答 2026 v1'
export const APP_BRAND_ICON = '/favicon.svg?v=1'

export const normalizeBrandText = (value) => {
  if (typeof value !== 'string') return ''

  return value
    .replace(/Yuxi/gi, APP_BRAND_NAME)
    .replace(/语析/g, APP_BRAND_NAME)
    .replace(/开源且可私有部署/g, '支持私有部署')
    .replace(/开源\s*·\s*/g, '')
    .replace(/开源/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
}
