"""结构化日志的字段契约。

为什么这条要单独钉住：应用已经用 python-json-logger 打了 JSON 日志，
阶段 2 的可观测性校验（断言日志里有 endpoint / duration_ms、没有 ERROR）
就是建立在"这几个字段一定会出现"上的。字段名一改，那边的断言会**静默失效**
（少个 key 不会报错，只会让校验永远通过），所以在这里锁死。
"""
import io
import json
import logging

from pythonjsonlogger import jsonlogger


def test_log_request_emits_structured_fields(client, fake_douban, caplog):
    caplog.set_level(logging.INFO, logger='api')

    client.post('/crawl/douban')

    records = [
        r for r in caplog.records
        if r.name == 'api' and r.getMessage() == 'Request success'
    ]
    assert records, '没有捕获到 api 的 Request success 日志'

    rec = records[-1]
    assert rec.endpoint == 'api.crawl'
    assert rec.method == 'POST'
    # 精确值，不是 startswith：full_path 以前会带上一个孤零零的 '?'（'/crawl/douban?'），
    # 这个字段是阶段 2 要拿去做日志断言的东西，容不得噪音
    assert rec.path == '/crawl/douban'
    assert isinstance(rec.duration_ms, (int, float))


def test_json_formatter_outputs_parseable_json_with_extra_fields():
    """格式化器本身的契约：extra 里的字段要成为 JSON 的顶层 key。"""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        jsonlogger.JsonFormatter('%(message)s %(endpoint)s %(duration_ms)s')
    )
    logger = logging.getLogger('json-formatter-contract')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info('Request success', extra={'endpoint': 'api.crawl', 'duration_ms': 1.23})
    finally:
        logger.removeHandler(handler)

    payload = json.loads(stream.getvalue())
    assert payload['message'] == 'Request success'
    assert payload['endpoint'] == 'api.crawl'
    assert payload['duration_ms'] == 1.23
