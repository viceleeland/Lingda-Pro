from dataclasses import dataclass, field

from yuxi.agents.context import BaseContext


@dataclass(kw_only=True)
class ChatBotContext(BaseContext):
    enable_workspace_tools: bool = field(
        default=True,
        metadata={
            "name": "工作区工具",
            "description": "启用文件系统和待办工具；纯知识库问答可关闭以减少模型工具上下文。",
            "type": "boolean",
        },
    )

    enable_memory: bool = field(
        default=True,
        metadata={
            "name": "用户记忆",
            "description": "加载用户长期记忆及其读写工具；不需要跨会话记忆时可关闭。",
            "type": "boolean",
        },
    )

    enable_subagents: bool = field(
        default=True,
        metadata={
            "name": "子智能体",
            "description": "加载子智能体委派工具；专用知识库问答智能体可关闭。",
            "type": "boolean",
        },
    )

    subagents: list[str] | None = field(
        default=None,
        metadata={
            "name": "子智能体",
            "options": [],
            "description": "可选子智能体列表，为空表示启用当前用户可见的全部子智能体。",
            "type": "list",
            "kind": "subagents",
        },
    )
