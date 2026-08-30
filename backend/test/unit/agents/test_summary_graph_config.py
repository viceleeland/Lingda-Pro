from __future__ import annotations

from types import SimpleNamespace

import pytest

from yuxi.agents.buildin.chatbot import graph as chatbot_graph
from yuxi.agents.buildin.subagent import graph as subagent_graph


def _context(summary_threshold: int = 123) -> SimpleNamespace:
    return SimpleNamespace(
        model="test-provider:test-model",
        summary_threshold=summary_threshold,
        summary_keep_messages=7,
        summary_prompt="SUMMARY {messages}",
        summary_tool_result_token_limit=300,
        summary_l2_trigger_ratio=0.75,
        tool_token_limit=3,
        model_retry_times=1,
        workdir_relative_path="projects/11111111-1111-4111-8111-111111111111",
        workdir_path="/home/gem/user-data/projects/11111111-1111-4111-8111-111111111111",
    )


def _patch_common_graph_deps(monkeypatch: pytest.MonkeyPatch, graph_module, captured: dict) -> None:
    monkeypatch.setattr(graph_module, "load_chat_model", lambda fully_specified_name: object())
    monkeypatch.setattr(graph_module, "create_agent_filesystem_middleware", lambda *_args, **_kwargs: object())

    def create_summary_middleware(**kwargs):
        captured["summary_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(graph_module, "create_summary_middleware", create_summary_middleware)


@pytest.mark.parametrize(
    ("graph_module", "threshold", "build_args", "patch_subagent_task"),
    [
        (chatbot_graph, 123, (object(),), True),
        (subagent_graph, 64, (object(), "default"), False),
    ],
)
@pytest.mark.unit
@pytest.mark.asyncio
async def test_summary_trim_limit_matches_summary_threshold(
    monkeypatch: pytest.MonkeyPatch, graph_module, threshold: int, build_args, patch_subagent_task: bool
) -> None:
    captured: dict = {}
    _patch_common_graph_deps(monkeypatch, graph_module, captured)

    async def no_subagent_middleware(_context):
        return None

    if patch_subagent_task:
        monkeypatch.setattr(graph_module, "create_subagent_task_middleware", no_subagent_middleware)

    middlewares = await graph_module._build_middlewares(_context(summary_threshold=threshold), *build_args)

    assert captured["summary_kwargs"]["trigger"] == ("tokens", threshold * 1024)
    assert captured["summary_kwargs"]["trim_tokens_to_summarize"] == threshold * 1024
    assert captured["summary_kwargs"]["l1_l2_trigger_ratio"] == 0.75
    middleware_names = [type(middleware).__name__ for middleware in middlewares]
    assert middleware_names.index("ModelRetryMiddleware") < middleware_names.index("ImageInputCompatibilityMiddleware")


@pytest.mark.parametrize(
    ("graph_module", "build_args", "patch_subagent_task"),
    [
        (chatbot_graph, (object(),), True),
        (subagent_graph, (object(), "default"), False),
    ],
)
@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_retry_exhaustion_is_propagated(
    monkeypatch: pytest.MonkeyPatch,
    graph_module,
    build_args,
    patch_subagent_task: bool,
) -> None:
    captured: dict = {}
    _patch_common_graph_deps(monkeypatch, graph_module, captured)

    if patch_subagent_task:
        async def no_subagent_middleware(_context):
            return None

        monkeypatch.setattr(graph_module, "create_subagent_task_middleware", no_subagent_middleware)

    middlewares = await graph_module._build_middlewares(_context(), *build_args)
    retry_middleware = next(
        middleware for middleware in middlewares if type(middleware).__name__ == "ModelRetryMiddleware"
    )

    assert retry_middleware.on_failure == "error"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_knowledge_only_context_skips_workspace_memory_and_subagent_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    context.enable_workspace_tools = False
    context.enable_memory = False
    context.enable_subagents = False

    monkeypatch.setattr(chatbot_graph, "load_chat_model", lambda fully_specified_name: object())
    summary_kwargs = {}

    def create_summary_middleware(**kwargs):
        summary_kwargs.update(kwargs)
        return object()

    monkeypatch.setattr(chatbot_graph, "create_summary_middleware", create_summary_middleware)
    monkeypatch.setattr(
        chatbot_graph,
        "create_agent_filesystem_middleware",
        lambda *_args, **_kwargs: pytest.fail("workspace middleware must stay disabled"),
    )

    async def fail_memory(_context):
        pytest.fail("memory middleware must stay disabled")

    async def fail_subagents(_context):
        pytest.fail("subagent middleware must stay disabled")

    monkeypatch.setattr(chatbot_graph, "create_memory_middleware", fail_memory)
    monkeypatch.setattr(chatbot_graph, "create_subagent_task_middleware", fail_subagents)

    middlewares = await chatbot_graph._build_middlewares(context, object())
    middleware_names = [type(middleware).__name__ for middleware in middlewares]

    assert "SkillsMiddleware" in middleware_names
    assert "TodoListMiddleware" not in middleware_names
    assert summary_kwargs["tool_result_offload_token_limit"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sandbox_only_context_keeps_tool_results_inline_without_read_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    context.enable_workspace_tools = False
    context.enable_memory = False
    context.enable_subagents = False
    captured: dict = {}
    _patch_common_graph_deps(monkeypatch, chatbot_graph, captured)
    monkeypatch.setattr(chatbot_graph, "context_requires_workspace_runtime", lambda _context: True)

    async def no_subagent_middleware(_context):
        return None

    monkeypatch.setattr(chatbot_graph, "create_subagent_task_middleware", no_subagent_middleware)

    await chatbot_graph._build_middlewares(context, object())

    assert captured["summary_kwargs"]["tool_result_offload_token_limit"] is None
