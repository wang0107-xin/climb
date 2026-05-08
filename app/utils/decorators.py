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
                'path': request.full_path,
                'duration_ms': duration,
                'user': getattr(g, 'user', None)
            })
            return resp
        except Exception as e:
            logger.error('Request failed', exc_info=True)
            raise
    return decorated