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
        rec = execute_crawl(platform)
        return jsonify(rec.to_dict()), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500