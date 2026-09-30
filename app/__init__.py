import logging

from flask import Flask
from pythonjsonlogger import jsonlogger

from .config import config
from .extensions import cache, db
from .routes import bp


def create_app(config_name='development'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # 初始化扩展
    db.init_app(app)
    cache.init_app(app)

    # 注册蓝图
    app.register_blueprint(bp)

    # 日志配置
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(name)s %(levelname)s %(message)s %(endpoint)s %(method)s %(path)s %(duration_ms)s'
    )
    handler.setFormatter(formatter)

    for logger_name in ('api', 'werkzeug'):
        logger = logging.getLogger(logger_name)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG if app.debug else logging.INFO)

    # 初始化数据库
    with app.app_context():
        db.create_all()

    return app