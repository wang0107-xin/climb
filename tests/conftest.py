"""pytest 共享夹具。

有两个坑必须在**这里**解决，在测试用例里解决不了：

1. app/config.py 是在**类定义时**（也就是 import 时）就把 DATABASE_URL 读进
   Config.SQLALCHEMY_DATABASE_URI 了；而 config.py 里的 load_dotenv() 默认
   不覆盖已存在的环境变量（.env 已经被 git 跟踪，工作区里有一份）。
   所以 DATABASE_URL 必须在 import app **之前**设好，否则测的还是 .env 里的库。

2. 不能用 :memory:。config.py 的 SQLALCHEMY_ENGINE_OPTIONS 里带 pool_size，
   而 :memory: 用的是 StaticPool，不接受这个参数，会直接 TypeError
   （原 Jenkinsfile 里踩过一次，注释还留着）。所以统一用临时文件型 SQLite。

另外 reports/ 目录在这里创建：pytest 的 junitxml 插件是在 pytest_configure
阶段就打开报告文件的，比任何 fixture 都早；而根目录 conftest.py 的模块级代码
在它之前执行，所以在这里 mkdir 才是可靠的。
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# 报告目录：必须早于 pytest 打开 junit.xml
(BASE_DIR / 'reports').mkdir(exist_ok=True)

# ---- 必须在 import app 之前设置 ----
_TMP_DB_DIR = Path(tempfile.mkdtemp(prefix='pytest-db-'))
# as_posix() 是为了跨平台：Windows 上 sqlite:///C:/... 才认，反斜杠不认
os.environ['DATABASE_URL'] = 'sqlite:///' + (_TMP_DB_DIR / 'test.db').as_posix()
os.environ['SECRET_KEY'] = 'pytest-secret'
os.environ['FLASK_ENV'] = 'production'

from app import create_app  # noqa: E402
from app.extensions import cache, db  # noqa: E402
from app.services import crawler_service  # noqa: E402


@pytest.fixture(scope='session')
def app():
    application = create_app('production')
    yield application
    # 不 dispose 的话 pytest 退出时会报一堆 ResourceWarning: unclosed database
    with application.app_context():
        db.engine.dispose()
    shutil.rmtree(_TMP_DB_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolate(app, tmp_path, monkeypatch):
    """每个用例都从干净状态开始。

    三件事：

    - execute_crawl 带 @cache.memoize，不清缓存的话第二个用例会直接拿上一个用例的结果
    - 自带的 save_to_csv 写的是项目里的 data/，测试不能污染工作区，
      所以把 crawler_service 的 BASE / DATA_DIR 都改到用例自己的临时目录
    - 只改 DATA_DIR 不够：save_to_csv 里还有 path.relative_to(BASE)，
      临时目录在 BASE 外面会让它抛 ValueError
    """
    with app.app_context():
        db.drop_all()
        db.create_all()
        cache.clear()

    monkeypatch.setattr(crawler_service, 'BASE', tmp_path)
    monkeypatch.setattr(crawler_service, 'DATA_DIR', tmp_path / 'data')
    (tmp_path / 'data').mkdir()
    yield


@pytest.fixture
def client(app):
    return app.test_client()


FAKE_ROWS = [
    {'title': '肖申克的救赎', 'rating': '9.7', 'link': 'https://movie.douban.com/subject/1292052/'},
    {'title': '霸王别姬', 'rating': '9.6', 'link': 'https://movie.douban.com/subject/1291546/'},
]


@pytest.fixture
def fake_douban(monkeypatch):
    """把豆瓣抓取换成固定数据。

    单元测试一律不碰外网：真实网络会让流水线因为豆瓣改版或网络抖动而红，
    这种红没有信息量，只会让人学会忽略流水线。网络那部分留给节点冒烟。
    """
    from app.crawlers.douban import DoubanCrawler

    monkeypatch.setattr(DoubanCrawler, 'fetch_data', lambda self: [dict(r) for r in FAKE_ROWS])
    return FAKE_ROWS
