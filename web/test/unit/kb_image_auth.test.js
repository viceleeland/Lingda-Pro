import assert from 'node:assert/strict'
import test from 'node:test'

import { isAuthenticatedKbImageUrl } from '../../src/utils/kb_utils.js'

const origin = 'http://localhost:5173'
const imagePath = '/api/knowledge/databases/kb-1/images/kb-images/page_0001.png'

test('仅同源知识库图片地址可以携带认证头', () => {
  assert.equal(isAuthenticatedKbImageUrl(imagePath, origin), true)
  assert.equal(isAuthenticatedKbImageUrl(`${origin}${imagePath}`, origin), true)
  assert.equal(isAuthenticatedKbImageUrl(`https://attacker.example${imagePath}`, origin), false)
  assert.equal(isAuthenticatedKbImageUrl(`//attacker.example${imagePath}`, origin), false)
  assert.equal(isAuthenticatedKbImageUrl(`${origin}.attacker.example${imagePath}`, origin), false)
  assert.equal(isAuthenticatedKbImageUrl(`/preview?next=${encodeURIComponent(imagePath)}`, origin), false)
})
