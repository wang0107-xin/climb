import logging

from flask import Flask
from pythonjsonlogger import jsonlogger
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

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
    #
    # 这个 try 兜的是 gunicorn 多 worker 的**建表竞态**，不是"顺手吞个异常"：
    # CMD 是 `gunicorn --workers 2`，两个 worker 各自 import 一次本模块，于是
    # 两个进程同时对同一个空库跑 create_all。而 create_all 是"先查表在不在、
    # 再 CREATE TABLE"，两边会同时查到"不存在"然后抢着建，输的那个拿到
    # `table crawl_result already exists`。
    #
    # 它发生在 import 期，没有哪一层接得住：worker 起不来 → gunicorn 判定
    # "Worker failed to boot" 并让 master 退出（exit code 3）→ kubelet 重启
    # 容器 → 第二次启动时表已经在了，一切正常。现象就是「每次部署，Pod 都要
    # 重启 1~2 次」，而门禁里 `Pod 无重启` 那条会永远红。
    #
    # 但不能盲吞：只有"表确实已经全建好了"才算这个竞态，别的原因（库文件路径
    # 不对、磁盘只读、文件损坏）必须继续往上抛 —— "目标已达成"和"出事了"得是
    # 两种结果。
    with app.app_context():
        try:
            db.create_all()
        except OperationalError:
            existing = set(inspect(db.engine).get_table_names())
            if not set(db.metadata.tables).issubset(existing):
                raise

    return app