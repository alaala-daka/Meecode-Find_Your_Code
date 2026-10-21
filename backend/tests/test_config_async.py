import asyncio

from app import config


def test_llm_concurrency_defaults():
    assert config.LLM_MAX_CONCURRENCY == 200
    assert config.LLM_MAX_CONCURRENCY_PER_KEY == 20
    assert config.LLM_TIMEOUT == 120
    assert config.LLM_STREAM_TOTAL_TIMEOUT == 180
    assert config.URL_RESOLVE_TIMEOUT == 2
    assert config.URL_RESOLVE_MAX_CONCURRENCY == 8
    assert config.LLM_ACQUIRE_TIMEOUT == 10
    assert config.LLM_RESERVED_SEATS == 20


async def test_asyncio_mode_enabled():
    # pytest-asyncio auto 模式：async def 测试无需装饰器即可被收集运行
    await asyncio.sleep(0)
    assert True
