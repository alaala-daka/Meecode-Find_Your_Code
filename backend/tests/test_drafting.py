"""「AI 帮我写」草稿生成：正面文案、分类钳制、卖点裁剪、LLM 接线与错误传播。"""
import pytest

from app import config
from app.feed import drafting, llm
from app.feed.schemas import DraftGen, DraftResult


def test_mock_path_returns_non_empty_draft(monkeypatch):
    monkeypatch.setattr(config, "LLM_MOCK", True)
    res = drafting.draft_repo("demo/agent-runtime", "x" * 500, [], route="ai-draft")
    assert isinstance(res, DraftResult)
    assert res.tagline_zh and res.intro_zh
    assert res.suggested_category in config.CATEGORIES


def test_real_path_builds_positive_prompt_and_maps(monkeypatch):
    monkeypatch.setattr(config, "LLM_MOCK", False)
    captured = {}

    def fake_chat_json(*, system, user, model, route, repo_id=None):
        captured.update(system=system, user=user, model=model, route=route, repo_id=repo_id)
        return DraftGen(tagline_zh="卖点", intro_zh="介绍", category="数据处理")

    monkeypatch.setattr(llm, "chat_json", fake_chat_json)
    res = drafting.draft_repo("demo/x", "READ", [{"path": "a.py", "type": "blob"}],
                              route="ai-draft", repo_id=7)
    assert "只写正面" in captured["system"]            # 正面约束
    assert "不写任何负面" in captured["system"]        # 禁负面约束
    assert "、".join(config.CATEGORIES) in captured["system"]
    assert "READ" in captured["user"] and "demo/x" in captured["user"]
    assert captured["model"] is DraftGen
    assert captured["route"] == "ai-draft" and captured["repo_id"] == 7
    assert res.tagline_zh == "卖点" and res.intro_zh == "介绍"
    assert res.suggested_category == "数据处理"


def test_unknown_category_clamped_to_other(monkeypatch):
    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(llm, "chat_json",
                        lambda **kw: DraftGen(tagline_zh="t", intro_zh="i", category="不存在"))
    res = drafting.draft_repo("demo/x", "", [], route="ai-draft")
    assert res.suggested_category == "其他"


def test_tagline_trimmed_to_40(monkeypatch):
    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(llm, "chat_json",
                        lambda **kw: DraftGen(tagline_zh="长" * 60, intro_zh="i", category="开发工具"))
    res = drafting.draft_repo("demo/x", "", [], route="ai-draft")
    assert len(res.tagline_zh) == 40


def test_llm_error_propagates_for_route_to_catch(monkeypatch):
    """draft_repo 不吞错：由 ai_draft 外层 try/except 兜底成空（绝不 500）。"""
    monkeypatch.setattr(config, "LLM_MOCK", False)

    def boom(**kw):
        raise RuntimeError("LLM 挂了")

    monkeypatch.setattr(llm, "chat_json", boom)
    with pytest.raises(RuntimeError):
        drafting.draft_repo("demo/x", "", [], route="ai-draft")
