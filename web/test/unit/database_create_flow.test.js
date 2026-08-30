import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildDatabaseRequest,
  createEmptyDatabaseForm,
  selectDatabaseType,
  validateDatabaseConfig
} from '../../src/utils/databaseCreateForm.js'
import { getKbTypeLabel } from '../../src/utils/kb_utils.js'

const difyType = {
  create_params: {
    options: [
      { key: 'url', label: '地址', required: true },
      { key: 'token', label: 'Token', type: 'password', required: true }
    ]
  }
}

test('切换知识库类型保留通用字段并重置类型参数', () => {
  const form = { ...createEmptyDatabaseForm('embed/model'), name: '产品资料', description: '说明' }
  const selected = selectDatabaseType(form, 'dify', difyType)
  assert.equal(selected.name, '产品资料')
  assert.equal(selected.description, '说明')
  assert.deepEqual(selected.additional_params, { url: '', token: '' })
})

test('配置校验拒绝空名称和必填动态字段', () => {
  const empty = selectDatabaseType(createEmptyDatabaseForm(), 'dify', difyType)
  assert.equal(validateDatabaseConfig(empty, difyType), '请输入知识库名称')
  empty.name = '资料'
  assert.equal(validateDatabaseConfig(empty, difyType), '请填写地址')
})

test('只为需要嵌入模型的类型构建模型和分块参数', () => {
  const form = {
    ...createEmptyDatabaseForm('embed/model'),
    name: '资料',
    kb_type: 'milvus',
    chunk_preset_id: 'general'
  }
  const request = buildDatabaseRequest(
    form,
    { requires_embedding_model: true, create_params: { options: [] } },
    { version: 2 },
    'fallback/model'
  )
  assert.equal(request.embedding_model_spec, 'embed/model')
  assert.equal(request.additional_params.chunk_preset_id, 'general')

  const connectorRequest = buildDatabaseRequest(
    { ...form, kb_type: 'dify' },
    difyType,
    { version: 2 },
    'fallback/model'
  )
  assert.equal('embedding_model_spec' in connectorRequest, false)
  assert.equal('chunk_preset_id' in connectorRequest.additional_params, false)
})

test('知识库类型标签映射将 milvus 解析为向量知识库', () => {
  assert.equal(getKbTypeLabel('milvus'), '向量知识库')
  assert.equal(getKbTypeLabel('Milvus'), '向量知识库')
  assert.equal(getKbTypeLabel('dify'), 'Dify')
  assert.equal(getKbTypeLabel('notion'), 'Notion')
  assert.equal(getKbTypeLabel('unknown'), 'unknown')
})
