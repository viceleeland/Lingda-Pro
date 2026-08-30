from __future__ import annotations

from dataclasses import dataclass

from deepagents.backends import CompositeBackend, StateBackend
from deepagents.middleware.filesystem import (
    TOOLS_EXCLUDED_FROM_EVICTION,
    FilesystemMiddleware,
    FsToolName,
)

from yuxi.agents.backends.paths import runtime_workdir_path
from yuxi.agents.skills.service import refresh_user_skill_projection_async

from .sandbox import ProvisionerSandboxBackend

# Yuxi 在 DeepAgents 内建排除集之上额外豁免知识库文档工具结果，
# 避免 read_file/offload 循环：该工具自带分页与引用语义。
_TOOL_RESULT_EVICTION_EXEMPT_TOOLS = frozenset(TOOLS_EXCLUDED_FROM_EVICTION) | {"open_kb_document"}

# 文件工具 allowlist：显式排除 destructive delete。Yuxi backend 未实现 delete，
# 且删除语义需要审批与审计设计，开放前不应让模型看到该工具。
_AGENT_FS_TOOLS: tuple[FsToolName, ...] = (
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
    "execute",
)


class YuxiFilesystemMiddleware(FilesystemMiddleware):
    """Filesystem middleware that budgets large tool outputs before they hit model context."""

    def wrap_tool_call(self, request, handler):
        tool_result = handler(request)

        if request.tool_call["name"] in _TOOL_RESULT_EVICTION_EXEMPT_TOOLS:
            return tool_result
        if self._tool_token_limit_before_evict is None:
            return tool_result

        return self._intercept_large_tool_result(tool_result)

    async def awrap_tool_call(self, request, handler):
        tool_result = await handler(request)

        if request.tool_call["name"] in _TOOL_RESULT_EVICTION_EXEMPT_TOOLS:
            return tool_result
        if self._tool_token_limit_before_evict is None:
            return tool_result

        return await self._aintercept_large_tool_result(tool_result)


@dataclass(frozen=True)
class _BackendScope:
    runtime_scope_id: str
    workdir_relative_path: str
    uid: str

    @property
    def workdir_path(self) -> str:
        return runtime_workdir_path(self.workdir_relative_path)

    @classmethod
    def from_sources(cls, *sources, error_context: str) -> _BackendScope:
        def string_value(key: str) -> str | None:
            for source in sources:
                value = source.get(key) if isinstance(source, dict) else getattr(source, key, None)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return None

        thread_id = string_value("thread_id")
        if not thread_id:
            raise ValueError(f"thread_id is required in {error_context}")

        uid = string_value("uid")
        if not uid:
            raise ValueError(f"uid is required in {error_context}")

        runtime_scope_id = string_value("runtime_scope_id") or thread_id
        relative_path = string_value("workdir_relative_path") or ""
        return cls(
            runtime_scope_id=runtime_scope_id,
            workdir_relative_path=relative_path,
            uid=uid,
        )

    def create_backend(self) -> CompositeBackend:
        if not self.workdir_relative_path:
            raise ValueError("workdir path is required in runtime context")
        # artifacts_root 指向 outputs 目录：Filesystem/Summarization middleware 由此
        # 派生 large_tool_results 与 conversation_history 前缀，与 Yuxi 契约一致。
        return CompositeBackend(
            default=ProvisionerSandboxBackend(
                thread_id=self.runtime_scope_id,
                uid=self.uid,
                workdir_path=self.workdir_relative_path,
                create_if_missing=False,
            ),
            routes={},
            artifacts_root=f"{self.workdir_path.rstrip('/')}/outputs",
        )


def context_requires_workspace_runtime(context) -> bool:
    """Return whether an Agent may create or share a sandbox-backed workspace."""
    workspace_tools_enabled = bool(getattr(context, "enable_workspace_tools", True))
    subagents_enabled = bool(getattr(context, "enable_subagents", True))
    if workspace_tools_enabled or subagents_enabled:
        return True

    skill_scope = getattr(context, "_skill_runtime_snapshot", None)
    if not isinstance(skill_scope, dict):
        skill_scope = {
            "effective_skills": getattr(context, "_effective_skill_slugs", []) or [],
            "runtime_skills": getattr(context, "_runtime_skills", {}) or {},
        }
    tool_names = {
        str(tool_name).strip()
        for tool_name in (getattr(context, "tools", None) or [])
        if str(tool_name).strip()
    }
    runtime_skills = skill_scope.get("runtime_skills") or {}
    from yuxi.agents.skills.runtime import resolve_usable_skill_slugs

    for slug in resolve_usable_skill_slugs(context):
        tool_names.update((runtime_skills.get(slug) or {}).get("tools") or [])

    from yuxi.agents.toolkits.registry import get_extra_metadata

    for tool_name in tool_names:
        metadata = get_extra_metadata(tool_name)
        if metadata and metadata.requires_workspace_runtime:
            return True
    return False


async def sync_agent_context_skills(context) -> None:
    """在 Agent Run 初始化时同步当前用户获授权的共享 Skill 投影。"""
    scope = _BackendScope.from_sources(context, error_context="runtime context")
    await refresh_user_skill_projection_async(scope.uid)


def create_agent_composite_backend(context) -> CompositeBackend:
    """按已准备的 Agent context 构造本 Run 独享的 CompositeBackend 实例。

    DeepAgents 0.7 移除了 backend factory：每次 graph 构造时基于 context 创建
    具体实例。工作区 Agent 使用沙箱；纯知识库 Agent 使用 checkpointed state，
    让 summary 仍可安全落盘而无需物化 Docker runtime。
    """
    if not context_requires_workspace_runtime(context):
        return CompositeBackend(default=StateBackend(), routes={}, artifacts_root="/outputs")

    return _BackendScope.from_sources(context, error_context="agent context").create_backend()


def create_agent_filesystem_middleware(
    tool_token_limit_before_evict: int | None = None,
    *,
    backend: CompositeBackend,
) -> FilesystemMiddleware:
    return YuxiFilesystemMiddleware(
        backend=backend,
        tool_token_limit_before_evict=tool_token_limit_before_evict,
        tools=list(_AGENT_FS_TOOLS),
    )
