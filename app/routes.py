from flask import Blueprint, jsonify

from .services.crawler_service import execute_crawl
from .utils.decorators import log_request

bp = Blueprint('api', __name__)

@bp.route('/')
def home():
    return {'msg': 'Flask Crawler API Running'}

@bp.route('/crawl/<platform>', methods=['POST'])
@log_request
def crawl(platform):
    try:
        # execute_crawl 返回的已经是拍平好的 dict（见那边的注释：缓存里不能放 ORM 对象）
        return jsonify(execute_crawl(platform)), 201
    # 这里盲吞是刻意的（BLE001）：路由是 HTTP 边界，任何没预料到的异常都该变成
    # "一个 500 + 一句原因"，而不是 Flask 的 HTML 报错页。
    #
    # ⚠️ 但这条路有个已知的洞，阶段 2.4（可观测性 L1）会碰它：
    #    异常被这里吞掉之后**没有留下任何日志** —— log_request 那个装饰器只在异常
    #    穿过它的时候才记 'Request failed'，而这里不抛。于是服务端日志里一行都没有，
    #    只有客户端看见 500。L1 想断言"日志里没有 ERROR"，而这里是"什么日志都没有"，
    #    那种断言恰好抓不住它 —— 这也是为什么 L1 还得有一条"结构化日志字段完整"。
    except Exception as e:  # noqa: BLE001
        return jsonify({'error': str(e)}), 500