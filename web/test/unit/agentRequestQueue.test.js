import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { after, before, test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { createServer } from 'vite'

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
let server
let agentApi
let useAgentRequestQueue
let useAgentRunStream
let useAgentStreamHandler
let getStreamErrorMessage

before(async () => {
  const storage = new Map()
  globalThis.localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key)
  }
  server = await createServer({ root: webRoot, server: { middlewareMode: true } })
  ;({ agentApi } = await server.ssrLoadModule('/src/apis/index.js'))
  ;({ useAgentRequestQueue } = await server.ssrLoadModule(
    '/src/composables/useAgentRequestQueue.js'
  ))
  ;({ useAgentRunStream } = await server.ssrLoadModule('/src/composables/useAgentRunStream.js'))
  ;({ useAgentStreamHandler, getStreamErrorMessage } = await server.ssrLoadModule(
    '/src/composables/useAgentStreamHandler.js'
  ))
})

after(async () => {
  await server?.close()
  delete globalThis.localStorage
})

/** 集中 Run SSE 测试的固定依赖，只暴露各用例关心的行为。 */
const createRunStream = ({ threadState, handleStreamChunk, resetOnGoingConv }) =>
  useAgentRunStream({
    getThreadState: () => threadState,
    currentAgentId: { value: 'agent-1' },
    handleStreamChunk,
    fetchThreadMessages: async () => {},
    fetchAgentState: () => {},
    resetOnGoingConv,
    onScrollToBottom: () => {},
    streamSmoother: { flushThread: () => {} }
  })

test('agent_state SSE 使在途状态请求失效', () => {
  const threadState = {
    agentState: null,
    agentStateRequestVersion: 4,
    onGoingConv: { msgChunks: {} }
  }
  const { handleStreamChunk } = useAgentStreamHandler({
    getThreadState: () => threadState,
    processApprovalInStream: () => false,
    currentAgentId: { value: 'agent-1' },
    supportsFiles: { value: false }
  })
  const agentState = { token_usage: { measured_at: '2026-08-09T00:00:00Z' } }

  handleStreamChunk({ status: 'agent_state', agent_state: agentState }, 'thread-1')

  assert.deepEqual(threadState.agentState, agentState)
  assert.equal(threadState.agentStateRequestVersion, 5)
})

test('response_complete stops the reply indicator while the run remains active', () => {
  const threadState = {
    isStreaming: true,
    activeRunSteerable: true,
    responseCompleted: false,
    replyLoadingVisible: true,
    contextCompressing: false,
    onGoingConv: { msgChunks: {} }
  }
  let flushCount = 0
  const { handleStreamChunk } = useAgentStreamHandler({
    getThreadState: () => threadState,
    processApprovalInStream: () => false,
    currentAgentId: { value: 'agent-1' },
    supportsFiles: { value: false },
    streamSmoother: { flushThread: () => flushCount++ }
  })

  const shouldStop = handleStreamChunk({ status: 'response_complete' }, 'thread-1')

  assert.equal(shouldStop, false)
  assert.equal(flushCount, 1)
  assert.equal(threadState.replyLoadingVisible, false)
  assert.equal(threadState.isStreaming, true)
  assert.equal(threadState.activeRunSteerable, false)
  assert.equal(threadState.responseCompleted, true)
})

test('response_complete 尾部只保留有内容的发送动作并提供按钮可访问名称', () => {
  const chatSource = readFileSync(
    path.join(webRoot, 'src/components/AgentChatComponent.vue'),
    'utf8'
  )
  const inputSource = readFileSync(
    path.join(webRoot, 'src/components/MessageInputComponent.vue'),
    'utf8'
  )

  assert.match(
    chatSource,
    /const canStopActiveRun = computed\([\s\S]*?responseCompleted !== true[\s\S]*?const shouldShowStopButton = computed\(\s*\(\) => canStopActiveRun\.value/
  )
  assert.match(
    chatSource,
    /!String\(userInput\.value \|\| ''\)\.trim\(\) && !shouldShowStopButton\.value/
  )
  assert.match(inputSource, /:aria-label="sendButtonLabel"/)
  assert.match(
    inputSource,
    /const sendButtonLabel = computed\(\(\) => \(props\.isLoading \? '停止回答' : '发送消息'\)\)/
  )
})

test('response_complete 后的持久化错误保留服务端错误详情并终止运行', () => {
  const threadState = {
    isStreaming: true,
    replyLoadingVisible: true,
    pendingRequestId: 'request-1',
    contextCompressing: false,
    onGoingConv: { msgChunks: {} }
  }
  const reportedErrors = []
  const { handleStreamChunk } = useAgentStreamHandler({
    getThreadState: () => threadState,
    processApprovalInStream: () => false,
    currentAgentId: { value: 'agent-1' },
    supportsFiles: { value: false },
    streamSmoother: { flushThread: () => {} },
    reportChatError: ({ message }) => reportedErrors.push(message)
  })
  const errorChunk = {
    status: 'error',
    error_type: 'output_persistence_error',
    error_message: '最终输出持久化或绑定失败'
  }

  assert.equal(handleStreamChunk({ status: 'response_complete' }, 'thread-1'), false)
  assert.equal(getStreamErrorMessage(errorChunk), '最终输出持久化或绑定失败')
  assert.equal(handleStreamChunk(errorChunk, 'thread-1'), true)
  assert.deepEqual(reportedErrors, ['最终输出持久化或绑定失败'])
  assert.equal(threadState.isStreaming, false)
  assert.equal(threadState.pendingRequestId, null)
})

test('未知 worker 错误不向前端泄露内部异常详情', () => {
  assert.equal(
    getStreamErrorMessage({
      status: 'error',
      error_type: 'worker_error',
      error_message: 'database connection failed at postgresql://internal-host',
      message: 'resume failed at D:\\workspace\\yuxi\\runtime'
    }),
    '流式处理失败'
  )
})

test('run_created 立即完成状态交接并订阅新 Run SSE', async () => {
  const threadState = {
    queuedRequests: [{ request_id: 'request-1', status: 'queued' }],
    requestStreams: {},
    onGoingConv: { msgChunks: { old: [] } },
    pendingRequestId: null
  }
  const calls = []
  const originalStreamRequestEvents = agentApi.streamRequestEvents
  agentApi.streamRequestEvents = async () =>
    new Response('event: run_created\ndata: {"run_id":"run-2"}\n\n', {
      headers: { 'Content-Type': 'text/event-stream' }
    })

  try {
    const queue = useAgentRequestQueue({
      getThreadState: () => threadState,
      resetOnGoingConv: (threadId, options) => {
        calls.push(['reset', threadId, options])
        threadState.onGoingConv = { msgChunks: {} }
      },
      startRunStream: (...args) => {
        calls.push(['start', ...args])
      },
      onStreamError: () => {}
    })

    await queue.startRequestStream('thread-1', 'request-1')

    assert.deepEqual(calls, [
      ['reset', 'thread-1', { preserveRequestStreams: true }],
      ['start', 'thread-1', 'run-2', '0-0']
    ])
    assert.equal(threadState.pendingRequestId, 'request-1')
    assert.deepEqual(threadState.queuedRequests, [])
  } finally {
    agentApi.streamRequestEvents = originalStreamRequestEvents
  }
})

test('run_created 先到达时保留旧 Run 已渲染的内容', async () => {
  const oldMessages = { 'old-message': [{ id: 'old-message', content: '旧回复' }] }
  const threadState = {
    activeRunId: 'run-1',
    queuedRequests: [{ request_id: 'request-2', status: 'queued' }],
    requestStreams: {},
    onGoingConv: { msgChunks: oldMessages },
    pendingRequestId: null
  }
  const calls = []
  const originalStreamRequestEvents = agentApi.streamRequestEvents
  agentApi.streamRequestEvents = async () =>
    new Response('event: run_created\ndata: {"run_id":"run-2"}\n\n', {
      headers: { 'Content-Type': 'text/event-stream' }
    })

  try {
    const queue = useAgentRequestQueue({
      getThreadState: () => threadState,
      resetOnGoingConv: () => calls.push(['reset']),
      startRunStream: (...args) => calls.push(['start', ...args]),
      onStreamError: () => {}
    })

    await queue.startRequestStream('thread-1', 'request-2')

    assert.deepEqual(calls, [['start', 'thread-1', 'run-2', '0-0']])
    assert.equal(threadState.onGoingConv.msgChunks, oldMessages)
    assert.equal(threadState.pendingRequestId, 'request-2')
  } finally {
    agentApi.streamRequestEvents = originalStreamRequestEvents
  }
})

test('replacement Run SSE 的增量 chunk 会连续进入前端渲染处理', async () => {
  const oldMessages = { 'old-message': [{ id: 'old-message', content: '旧回复' }] }
  const threadState = {
    activeRunId: 'run-1',
    activeRunSteerable: true,
    queuedRequests: [{ request_id: 'request-2', status: 'queued' }],
    requestStreams: {},
    runLastSeq: '0-0',
    runStreamAbortController: null,
    replyLoadingVisible: true,
    pendingRequestId: 'request-1',
    pendingInterrupt: null,
    onGoingConv: { msgChunks: oldMessages }
  }
  const originalStreamRequestEvents = agentApi.streamRequestEvents
  const originalStreamAgentRunEvents = agentApi.streamAgentRunEvents
  const textEncoder = new TextEncoder()
  let runStreamController
  let replacementRun
  let loadingChunkCount = 0
  let resolveFirstChunk
  let resolveSecondChunk
  const firstChunkProcessed = new Promise((resolve) => {
    resolveFirstChunk = resolve
  })
  const secondChunkProcessed = new Promise((resolve) => {
    resolveSecondChunk = resolve
  })

  agentApi.streamRequestEvents = async () =>
    new Response('event: run_created\ndata: {"run_id":"run-2"}\n\n', {
      headers: { 'Content-Type': 'text/event-stream' }
    })
  agentApi.streamAgentRunEvents = async () =>
    new Response(
      new ReadableStream({
        start(controller) {
          runStreamController = controller
        }
      }),
      { headers: { 'Content-Type': 'text/event-stream' } }
    )

  try {
    const { handleStreamChunk } = useAgentStreamHandler({
      getThreadState: () => threadState,
      processApprovalInStream: () => false,
      currentAgentId: { value: 'agent-1' },
      supportsFiles: { value: false }
    })
    const runStream = createRunStream({
      threadState,
      handleStreamChunk: (chunk, threadId) => {
        const shouldStop = handleStreamChunk(chunk, threadId)
        if (chunk.status === 'loading') {
          loadingChunkCount += 1
          if (loadingChunkCount === 1) resolveFirstChunk()
          if (loadingChunkCount === 2) resolveSecondChunk()
        }
        return shouldStop
      },
      resetOnGoingConv: () => {}
    })
    const queue = useAgentRequestQueue({
      getThreadState: () => threadState,
      resetOnGoingConv: () => {},
      startRunStream: (...args) => {
        replacementRun = runStream.startRunStream(...args)
        return replacementRun
      },
      onStreamError: () => {}
    })

    await queue.startRequestStream('thread-1', 'request-2')

    runStreamController.enqueue(
      textEncoder.encode(
        'id: 1-0\nevent: custom\ndata: {"run_id":"run-2","request_id":"request-2","payload":{"chunk":{"status":"loading","run_id":"run-2","request_id":"request-2","stream_event":{"type":"message_delta","message_id":"assistant-2","content":"流式"}}}}\n\n'
      )
    )
    await firstChunkProcessed
    assert.deepEqual(
      threadState.onGoingConv.msgChunks['assistant-2'].map((chunk) => chunk.content),
      ['流式']
    )

    runStreamController.enqueue(
      textEncoder.encode(
        'id: 2-0\nevent: custom\ndata: {"run_id":"run-2","request_id":"request-2","payload":{"chunk":{"status":"loading","run_id":"run-2","request_id":"request-2","stream_event":{"type":"message_delta","message_id":"assistant-2","content":"渲染"}}}}\n\n'
      )
    )
    await secondChunkProcessed
    assert.deepEqual(
      threadState.onGoingConv.msgChunks['assistant-2'].map((chunk) => chunk.content),
      ['流式', '渲染']
    )

    runStreamController.enqueue(
      textEncoder.encode(
        'id: 3-0\nevent: end\ndata: {"run_id":"run-2","payload":{"status":"completed"}}\n\n'
      )
    )
    runStreamController.close()
    await replacementRun

    assert.deepEqual(threadState.onGoingConv.msgChunks['old-message'], [
      { id: 'old-message', content: '旧回复' }
    ])
    assert.equal(threadState.runLastSeq, '3-0')
  } finally {
    agentApi.streamRequestEvents = originalStreamRequestEvents
    agentApi.streamAgentRunEvents = originalStreamAgentRunEvents
  }
})

test('旧 Run 的延迟 AbortError 不覆盖新 Run 状态', async () => {
  const threadState = {
    activeRunId: null,
    activeRunSteerable: false,
    runLastSeq: '0-0',
    runStreamAbortController: null,
    replyLoadingVisible: false,
    pendingRequestId: null,
    onGoingConv: { msgChunks: {} }
  }
  const streamControllers = new Map()
  const originalStreamAgentRunEvents = agentApi.streamAgentRunEvents
  agentApi.streamAgentRunEvents = async (runId, _afterSeq, { signal }) =>
    new Response(
      new ReadableStream({
        start(controller) {
          streamControllers.set(runId, controller)
          signal.addEventListener('abort', () => {
            const delay = runId === 'run-1' ? 10 : 0
            setTimeout(() => controller.error(new DOMException('aborted', 'AbortError')), delay)
          })
          if (runId === 'run-2') {
            controller.enqueue(
              new TextEncoder().encode(
                'event: custom\ndata: {"run_id":"run-2","request_id":"request-2","payload":{"chunk":{"status":"init","msg":{"type":"human","content":"new"}}}}\n\n'
              )
            )
          }
        }
      }),
      { headers: { 'Content-Type': 'text/event-stream' } }
    )

  const runStream = createRunStream({
    threadState,
    handleStreamChunk: (chunk) => {
      if (chunk.status !== 'init') return
      threadState.pendingRequestId = chunk.request_id
      threadState.replyLoadingVisible = true
    },
    resetOnGoingConv: () => {}
  })

  try {
    const oldRun = runStream.startRunStream('thread-1', 'run-1')
    await new Promise((resolve) => setTimeout(resolve, 0))
    const newRun = runStream.startRunStream('thread-1', 'run-2')
    await new Promise((resolve) => setTimeout(resolve, 20))

    assert.equal(threadState.activeRunId, 'run-2')
    assert.equal(threadState.pendingRequestId, 'request-2')
    assert.equal(threadState.replyLoadingVisible, true)

    threadState.runStreamAbortController.abort()
    await Promise.allSettled([oldRun, newRun])
  } finally {
    agentApi.streamAgentRunEvents = originalStreamAgentRunEvents
  }
})

test('旧 Run 终态清理保留排队 Request SSE', async () => {
  const threadState = {
    activeRunId: null,
    activeRunSteerable: false,
    runLastSeq: '0-0',
    runStreamAbortController: null,
    replyLoadingVisible: false,
    pendingRequestId: null,
    pendingInterrupt: null,
    requestStreams: { 'request-2': { controller: new AbortController() } }
  }
  const resetCalls = []
  const originalStreamAgentRunEvents = agentApi.streamAgentRunEvents
  agentApi.streamAgentRunEvents = async () =>
    new Response('event: end\ndata: {"run_id":"run-1","payload":{"status":"completed"}}\n\n', {
      headers: { 'Content-Type': 'text/event-stream' }
    })

  try {
    const runStream = createRunStream({
      threadState,
      handleStreamChunk: () => {},
      resetOnGoingConv: (_threadId, options) => resetCalls.push(options)
    })

    await runStream.startRunStream('thread-1', 'run-1')
    await new Promise((resolve) => setTimeout(resolve, 0))

    assert.deepEqual(resetCalls, [{ preserveRequestStreams: true }])
    assert.equal(threadState.requestStreams['request-2'].controller.signal.aborted, false)
  } finally {
    agentApi.streamAgentRunEvents = originalStreamAgentRunEvents
  }
})
