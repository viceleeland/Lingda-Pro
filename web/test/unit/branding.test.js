import assert from 'node:assert/strict'
import test from 'node:test'

import {
  APP_BRAND_ICON,
  APP_BRAND_NAME,
  APP_COPYRIGHT,
  normalizeBrandText
} from '../../src/utils/branding.js'

test('旧品牌和开源宣传文案统一收敛为灵答品牌', () => {
  assert.equal(APP_BRAND_NAME, '灵答')
  assert.equal(APP_COPYRIGHT, '© 灵答 2026 v1')
  assert.equal(APP_BRAND_ICON, '/favicon.svg?v=1')
  assert.equal(normalizeBrandText('语析，与知识对话'), '灵答，与知识对话')
  assert.equal(normalizeBrandText('Yuxi，开源且可私有部署'), '灵答，支持私有部署')
})
