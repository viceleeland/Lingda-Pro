from __future__ import annotations

from types import SimpleNamespace

import pytest

import yuxi.agents.backends.knowledge_base_backend as knowledge_base_backend
from yuxi.knowledge.read_models import KnowledgeBaseSummary


@pytest.mark.asyncio
async def test_resolve_visible_knowledge_bases_filters_by_kb_id(monkeypatch):
    import yuxi.knowledge.runtime as knowledge_runtime

    async def fake_get_databases_by_uid(_uid):
        return [
            KnowledgeBaseSummary(
                kb_id="different-id",
                name="Legacy",
                description=None,
                kb_type="milvus",
                embedding_model_spec=None,
                llm_model_spec=None,
                query_params={},
                additional_params={},
                share_config={"version": 2, "read_scope": None, "manage_scope": None},
                created_by=None,
                created_at=None,
            )
        ]

    monkeypatch.setattr(knowledge_runtime.knowledge_base, "get_databases_by_uid", fake_get_databases_by_uid)

    context = SimpleNamespace(uid="u1", knowledges=["legacy-id"])

    databases = await knowledge_base_backend.resolve_visible_knowledge_bases_for_context(context)

    assert databases == []


@pytest.mark.asyncio
async def test_resolve_visible_knowledge_bases_reuses_current_database_session(monkeypatch):
    import yuxi.knowledge.runtime as knowledge_runtime

    expected_db = object()
    expected_user = SimpleNamespace(uid="u1")
    calls = []

    async def fake_get_databases_by_user(user, *, db=None):
        calls.append((user, db))
        return []

    monkeypatch.setattr(knowledge_runtime.knowledge_base, "get_databases_by_user", fake_get_databases_by_user)

    context = SimpleNamespace(uid="u1", knowledges=[])
    databases = await knowledge_base_backend.resolve_visible_knowledge_bases_for_context(
        context,
        db=expected_db,
        user=expected_user,
    )

    assert databases == []
    assert calls == [(expected_user, expected_db)]
