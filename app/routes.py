from flask import Blueprint, jsonify, request
from .utils.decorators import log_request
from .services.crawler_service import execute_crawl

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
    except Exception as e:
        return jsonify({'error': str(e)}), 500