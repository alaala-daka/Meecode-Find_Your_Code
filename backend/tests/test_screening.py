"""筛选管道：规则粗筛用固定 fixture，LLM 精筛走 mock。不打真实网络。"""
import pytest

from app import config, llm_usage
from app.feed import screening

DAY = 86400
NOW = 1_700_000_000


def tree(n_code: int) -> list[dict]:
    items = [{"path": "README.md", "type": "blob", "size": 100}]
    items += [{"path": f"src/f{i}.py", "type": "blob", "size": 100} for i in range(n_code)]
    return items


def good(**kw) -> dict:
    base = {
        "full_name": "someone/real-project", "language": "Python", "topics": [],
        "stars": 30, "created_at": NOW - 7 * DAY, "pushed_at": NOW - 2 * DAY,
        "archived": False,
    }
    return {**base, **kw}


LONG_README = "这是一个真实项目的说明文档。" * 60  # 远超 500 字符


def test_star_velocity_is_per_week():
    assert screening.star_velocity(30, NOW - 7 * DAY, NOW) == pytest.approx(30.0)
    assert screening.star_velocity(30, NOW - 14 * DAY, NOW) == pytest.approx(15.0)


def test_star_velocity_brand_new_repo_no_division_error():
    # 刚创建（age≈0）不能除零；按至少 1 天计
    assert screening.star_velocity(5, NOW, NOW) > 0


def test_count_code_files_ignores_trees_and_docs():
    items = [
        {"path": "src", "type": "tree", "size": 0},
        {"path": "README.md", "type": "blob", "size": 10},
        {"path": "LICENSE", "type": "blob", "size": 10},
        {"path": "a.py", "type": "blob", "size": 10},
        {"path": "b.rs", "type": "blob", "size": 10},
    ]
    assert screening.count_code_files(items) == 2


def test_accepts_qualified_repo():
    ok, why = screening.passes_rules(good(), LONG_README, tree(8), followers=20, now=NOW)
    assert ok, why


def test_rejects_short_readme():
    ok, why = screening.passes_rules(good(), "太短", tree(8), followers=20, now=NOW)
    assert not ok and "README" in why


def test_rejects_too_few_code_files():
    ok, why = screening.passes_rules(good(), LONG_README, tree(2), followers=20, now=NOW)
    assert not ok and "代码文件" in why


def test_rejects_stale_repo():
    stale = good(pushed_at=NOW - 60 * DAY)
    ok, why = screening.passes_rules(stale, LONG_README, tree(8), followers=20, now=NOW)
    assert not ok and "提交" in why


def test_rejects_archived():
    ok, why = screening.passes_rules(good(archived=True), LONG_README, tree(8), 20, NOW)
    assert not ok and "归档" in why


def test_rejects_low_star_velocity():
    slow = good(stars=4, created_at=NOW - 60 * DAY)  # ≈0.47/周
    ok, why = screening.passes_rules(slow, LONG_README, tree(8), followers=20, now=NOW)
    assert not ok and "增速" in why


def test_rejects_famous_author():
    ok, why = screening.passes_rules(good(), LONG_README, tree(8), followers=9000, now=NOW)
    assert not ok and "followers" in why


def test_rejects_blacklisted_name():
    for name in ("me/awesome-python", "me/rust-tutorial", "me/my-dotfiles", "me/leetcode-notes"):
        ok, why = screening.passes_rules(good(full_name=name), LONG_README, tree(8), 20, NOW)
        assert not ok and "黑名单" in why, name


def test_blacklist_matches_whole_word_not_substring():
    # "resume" 不该误杀 "resumable-upload"
    ok, why = screening.passes_rules(
        good(full_name="me/resumable-upload"), LONG_README, tree(8), 20, NOW)
    assert ok, why


def test_rejects_blacklisted_topic():
    ok, why = screening.passes_rules(
        good(topics=["awesome", "list"]), LONG_README, tree(8), 20, NOW)
    assert not ok and "黑名单" in why


def test_screen_repo_mock_returns_valid_result(monkeypatch):
    monkeypatch.setattr(config, "LLM_MOCK", True)
    r = screening.screen_repo("demo/agent-runtime", LONG_README, tree(8),
                              route=llm_usage.ROUTE_SUBMIT_SCREEN)
    assert r.is_real_project is True
    assert r.category in config.CATEGORIES
    assert 1 <= r.quality <= 5
    assert r.tagline_zh


def test_screen_repo_clamps_out_of_range_quality(monkeypatch):
    """LLM 返回越界分数时夹到 1..5，不能污染排序公式。"""
    monkeypatch.setattr(config, "LLM_MOCK", False)
    from app.feed import schemas
    monkeypatch.setattr(screening.llm, "chat_json",
                        lambda **kw: schemas.ScreeningResult(
                            is_real_project=True, category="其他",
                            tagline_zh="x", why_zh="y", quality=99))
    assert screening.screen_repo("a/b", LONG_README, tree(8),
                                 route=llm_usage.ROUTE_SUBMIT_SCREEN).quality == 5


def test_screen_repo_unknown_category_falls_back(monkeypatch):
    monkeypatch.setattr(config, "LLM_MOCK", False)
    from app.feed import schemas
    monkeypatch.setattr(screening.llm, "chat_json",
                        lambda **kw: schemas.ScreeningResult(
                            is_real_project=True, category="编造的分类",
                            tagline_zh="x", why_zh="y", quality=4))
    assert screening.screen_repo("a/b", LONG_README, tree(8),
                                 route=llm_usage.ROUTE_SUBMIT_SCREEN).category == "其他"
