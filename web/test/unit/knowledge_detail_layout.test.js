import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

test('知识库详情复用共享 header 且主体保持全宽', () => {
  const source = readSource('../../src/views/DataBaseInfoView.vue')
  const layout = readSource('../../src/components/shared/ExtensionDetailLayout.vue')

  assert.match(source, /<ExtensionDetailLayout/)
  assert.match(
    source,
    /import ExtensionDetailLayout from '@\/components\/shared\/ExtensionDetailLayout\.vue'/
  )
  assert.match(source, /<template #breadcrumb>/)
  assert.match(source, /<template #actions>/)
  assert.match(source, /<template #panel-filetable>/)
  assert.match(source, /<template #panel-query>/)
  assert.match(source, /<template #panel-graph>/)
  assert.match(source, /<template #panel-evaluation>/)
  assert.doesNotMatch(source, /<template #panel-benchmarks>/)
  assert.doesNotMatch(source, /class="detail-top-bar"/)
  assert.doesNotMatch(source, /class="database-tab-bar"/)
  assert.doesNotMatch(source, /extension-detail-view/)
  assert.match(
    source,
    /\.database-info-container,\s*\.knowledge-detail-layout \{[\s\S]*?width: 100%;[\s\S]*?height: 100%;/
  )
  assert.match(
    layout,
    /<a-tab-pane v-for="tab in tabs" :key="tab\.key" :force-render="tab\.forceRender === true">/
  )
  assert.match(source, /availableTabs\.some\(\(tab\) => tab\.key === requestedTab\)/)
  assert.match(
    source,
    /loaded && requestedTab && requestedTab !== activeTab\.value[\s\S]*?section: activeTab\.value/
  )
})

test('思维导图从 FileTable header 打开弹窗且不再占用一级 Tab', () => {
  const detailSource = readSource('../../src/views/DataBaseInfoView.vue')
  const fileTableSource = readSource('../../src/components/FileTable.vue')

  assert.match(fileTableSource, /<template #toolbar-actions>/)
  assert.match(fileTableSource, /class="[^"]*file-table-mindmap-button[^"]*"/)
  assert.match(fileTableSource, /@click="emit\('mindmap'\)"/)
  assert.match(fileTableSource, /const emit = defineEmits\(\['mindmap', 'search'\]\)/)
  assert.match(detailSource, /@mindmap="mindmapModalVisible = true"/)
  assert.match(detailSource, /v-model:open="mindmapModalVisible"/)
  assert.match(detailSource, /<MindMapSection v-if="kbId" :kb-id="kbId"/)
  assert.doesNotMatch(detailSource, /key: 'mindmap'/)
  assert.doesNotMatch(detailSource, /#panel-mindmap/)
})

test('只读连接器没有知识库详情入口并拒绝直接详情 URL', () => {
  const listSource = readSource('../../src/views/DataBaseView.vue')
  const detailSource = readSource('../../src/views/DataBaseInfoView.vue')

  assert.match(listSource, /:disabled="kbUtils\.isReadOnlyDatabase\(database\)"/)
  assert.match(
    listSource,
    /const navigateToDatabase = \(database\) => \{\s*if \(kbUtils\.isReadOnlyDatabase\(database\)\) return/
  )
  assert.match(listSource, /<a-menu-item v-if="database\.can_manage" key="edit">/)
  assert.match(
    detailSource,
    /store\.database\?\.kb_id === nextKbId &&[\s\S]*?kbUtils\.isReadOnlyDatabase\(store\.database\)[\s\S]*?route\.query\.action === 'edit' && canManageDatabase\.value[\s\S]*?showEditModal\(\)[\s\S]*?router\.replace\(\{ path: '\/extensions', query: \{ tab: 'knowledge' \} \}\)/
  )
  assert.match(
    detailSource,
    /action !== 'edit' \|\| loading \|\| !loaded \|\| !canManageDatabase\.value/
  )
  assert.match(detailSource, /@after-close="handleEditModalAfterClose"/)
  assert.match(
    detailSource,
    /const handleEditModalAfterClose = \(\) => \{\s*if \(isConnector\.value\) backToDatabase\(\)/
  )
})

test('检索面板强制挂载以保留上传后的示例问题生成', () => {
  const detailSource = readSource('../../src/views/DataBaseInfoView.vue')
  const layoutSource = readSource('../../src/components/shared/ExtensionDetailLayout.vue')

  assert.match(detailSource, /key: 'query', label: '检索测试', icon: Search, forceRender: true/)
  assert.match(layoutSource, /:force-render="tab\.forceRender === true"/)
})

test('检索结果使用 MarkdownPreview 展示知识库图片', () => {
  const source = readSource('../../src/components/QuerySection.vue')

  assert.match(source, /<MarkdownPreview :content="chunk\.content \|\| ''" class="result-content"/)
  assert.match(
    source,
    /import MarkdownPreview from '@\/components\/common\/MarkdownPreview\.vue'/
  )
  assert.doesNotMatch(source, /\{\{\s*chunk\.content\s*\}\}/)
})

test('图谱构建完成后自动刷新当前知识库画布', () => {
  const source = readSource('../../src/components/KnowledgeGraphSection.vue')
  const startBuildSource = source.slice(
    source.indexOf('const startGraphBuild = async'),
    source.indexOf('const retryGraphVectors = async')
  )

  assert.match(source, /watch\(\s*isBuildActive,\s*\(active, wasActive\) =>/)
  assert.match(
    source,
    /wasActive && graphBuildStatus\.value\?\.build_task_status === 'completed'[\s\S]*?scheduleGraphLoad\(0\)/
  )
  assert.match(
    startBuildSource,
    /graphBuildStatus\.value = \{[\s\S]*?build_task_status: 'pending'[\s\S]*?await loadGraphBuildStatus\(\)/
  )
})

test('思维导图弹窗销毁时取消延迟渲染任务和迟到错误反馈', () => {
  const source = readSource('../../src/components/MindMapSection.vue')

  assert.match(source, /const pendingTimers = new Set\(\)/)
  assert.match(source, /const scheduleMountedTask = \(callback, delay\) =>/)
  assert.match(source, /pendingTimers\.forEach\(\(timer\) => clearTimeout\(timer\)\)/)
  assert.match(
    source,
    /onUnmounted\(\(\) => \{\s*unmounted = true\s*clearMountedTasks\(\)[\s\S]*?markmapInstance = null/
  )
  assert.doesNotMatch(source, /setTimeout\(\(\) => \{\s*renderMindmap/)
  assert.equal((source.match(/catch \(error\) \{\s*if \(unmounted\) return/g) || []).length, 4)
})

test('MCP 与 Skill 使用移动后的共享详情布局', () => {
  const mcpSource = readSource('../../src/components/extensions/McpDetailView.vue')
  const skillSource = readSource('../../src/components/extensions/SkillDetailView.vue')

  for (const source of [mcpSource, skillSource]) {
    assert.match(
      source,
      /import ExtensionDetailLayout from '@\/components\/shared\/ExtensionDetailLayout\.vue'/
    )
  }
})
