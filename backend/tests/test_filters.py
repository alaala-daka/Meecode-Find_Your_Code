"""filters：URL 过滤参数白名单校验 + WHERE 片段生成（spec §3.1）。"""
import pytest
from fastapi import HTTPException

from app.feed import filters


def test_parse_defaults_are_no_filters():
    f = filters.parse_filters(None, None, None, None, None)
    assert f == filters.FeedFilters()
    cond, params = filters.filter_sql(f)
    assert cond == "" and params == []


def test_parse_lang_accepts_spaces_and_symbols():
    assert filters.parse_filters("Jupyter Notebook", None, None, None, None).lang == "Jupyter Notebook"
    assert filters.parse_filters("C++", None, None, None, None).lang == "C++"
    assert filters.parse_filters("  Python  ", None, None, None, None).lang == "Python"


@pytest.mark.parametrize("bad", ["", "py;drop", "语言", "a" * 31, "a%b"])
def test_parse_lang_rejects_bad_values(bad):
    with pytest.raises(HTTPException) as e:
        filters.parse_filters(bad, None, None, None, None)
    assert e.value.status_code == 422


def test_parse_topic_normalizes_lower_and_dedupes():
    f = filters.parse_filters(None, None, None, None, ["LLM", "llm", "Self-Hosted"])
    assert f.topics == ("llm", "self-hosted")


def test_parse_topic_caps_at_five():
    with pytest.raises(HTTPException):
        filters.parse_filters(None, None, None, None, ["t1", "t2", "t3", "t4", "t5", "t6"])


@pytest.mark.parametrize("bad", ["llm;--", "话题", "a" * 51, "a_b"])
def test_parse_topic_rejects_bad_values(bad):
    with pytest.raises(HTTPException):
        filters.parse_filters(None, None, None, None, [bad])


def test_parse_stars_valid_and_invalid():
    f = filters.parse_filters(None, 100, 500, None, None)
    assert f.stars == 100 and f.stars_max == 500
    with pytest.raises(HTTPException):
        filters.parse_filters(None, 500, 100, None, None)   # stars_max < stars
    with pytest.raises(HTTPException):
        filters.parse_filters(None, -1, None, None, None)
    with pytest.raises(HTTPException):
        filters.parse_filters(None, None, 10_000_001, None, None)


def test_parse_since_enum():
    assert filters.parse_filters(None, None, None, "ytd", None).since == "ytd"
    with pytest.raises(HTTPException):
        filters.parse_filters(None, None, None, "2024", None)
    with pytest.raises(HTTPException):
        filters.parse_filters(None, None, None, "7D", None)


def test_since_cutoff():
    now = 1_700_000_000            # 2023-11-14T22:13:20Z
    assert filters.since_cutoff(None, now) is None
    assert filters.since_cutoff("7d", now) == now - 7 * 86400
    assert filters.since_cutoff("30d", now) == now - 30 * 86400
    assert filters.since_cutoff("90d", now) == now - 90 * 86400
    assert filters.since_cutoff("ytd", now) == 1_672_531_200  # 2023-01-01T00:00:00Z


def test_filter_sql_full_combo():
    f = filters.parse_filters("Python", 100, 500, "30d", ["llm"])
    cond, params = filters.filter_sql(f)
    assert cond == (
        " AND LOWER(r.language) = LOWER(?)"
        " AND r.stars >= ?"
        " AND r.stars <= ?"
        " AND r.pushed_at >= ?"
        " AND (',' || r.topics || ',') LIKE ? ESCAPE '\\'"
    )
    assert params[0] == "Python"
    assert params[1] == 100 and params[2] == 500
    assert params[4] == "%,llm,%"
    assert params[3] == filters.since_cutoff("30d")


def test_filter_sql_topic_and_semantics():
    """多个 topic 是 AND（每条 LIKE 各占一个参数），不是 OR。"""
    f = filters.parse_filters(None, None, None, None, ["llm", "self-hosted"])
    cond, params = filters.filter_sql(f)
    assert cond.count("LIKE") == 2 and len(params) == 2
