import time
from functools import wraps
from flask import request, g
import logging

logger = logging.getLogger('api')

def log_request(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        start = time.time()
        try:
            resp = f(*args, **kwargs)
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
        except Exception as e:
            logger.error('Request failed', exc_info=True)
            raise
    return decorated