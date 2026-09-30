import logging
import time
from functools import wraps

from flask import g, request

logger = logging.getLogger('api')

def log_request(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        start = time.time()
        # try 里只放"可能失败的那一句"（调用业务函数），成功后的记账放在外面。
        # 原来的写法把 duration 计算、logger.info、return 全塞在 try 里，等于把"记账"
        # 也算进"可能失败"的范围 —— 记账自己要是炸了，会被下面那个 except 当成业务失败
        # 再记一条 'Request failed'，日志里就出现两条互相矛盾的记录。ruff 的 TRY300 指的就是这个。
        try:
            resp = f(*args, **kwargs)
        except Exception:
            # 这里 catch Exception 是刻意的：这个装饰器是请求的最外层，职责就是
            # "任何失败都要留下一条带栈的日志，然后原样抛上去"。
            # 它没有被 ruff 的 BLE001（盲吞异常）抓住，是因为它**重新抛了** ——
            # 记一笔再抛不算吞；routes.py 里那条只记不抛的才是。
            logger.exception('Request failed')
            raise
        duration = round((time.time() - start) * 1000, 2)
        logger.info('Request success', extra={
            'endpoint': request.endpoint,
            'method': request.method,
            # full_path 在没带查询串时会补一个孤零零的 '?'（'/crawl/douban?'）。
            # 这个字段是要进日志、被断言的东西，别让它带这种噪音。
            'path': request.full_path.rstrip('?'),
            'duration_ms': duration,
            'user': getattr(g, 'user', None)
        })
        return resp
    return decorated