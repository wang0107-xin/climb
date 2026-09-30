"""接口层用例：首页 + 抓取接口的成功/失败分支。"""
from types import SimpleNamespace

from app.models.result import CrawlResult
from app.services import crawler_service

# ---------------- 首页 ----------------

def test_home_returns_running_message(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert resp.get_json() == {'msg': 'Flask Crawler API Running'}


def test_home_is_json(client):
    assert client.get('/').mimetype == 'application/json'


def test_unknown_path_is_404(client):
    assert client.get('/no-such-path').status_code == 404


# ---------------- 抓取接口：成功分支 ----------------

def test_crawl_success_returns_201_and_record_fields(client, fake_douban):
    resp = client.post('/crawl/douban')
    assert resp.status_code == 201
    body = resp.get_json()
    assert body['platform'] == 'douban'
    assert body['count'] == len(fake_douban)
    assert body['file_path'].startswith('data/')
    assert body['file_path'].endswith('.csv')
    assert isinstance(body['id'], int)


def test_crawl_success_persists_record(client, fake_douban, app):
    client.post('/crawl/douban')
    with app.app_context():
        assert CrawlResult.query.count() == 1
        rec = CrawlResult.query.first()
        assert rec.platform == 'douban'
        assert rec.data['count'] == len(fake_douban)


def test_crawl_success_writes_csv(client, fake_douban, tmp_path):
    client.post('/crawl/douban')
    files = list((tmp_path / 'data').glob('douban_*.csv'))
    assert len(files) == 1
    lines = files[0].read_text(encoding='utf-8').strip().splitlines()
    assert lines[0] == 'title,rating,link'
    assert len(lines) == len(fake_douban) + 1


def test_crawl_only_accepts_post(client):
    assert client.get('/crawl/douban').status_code == 405


# ---------------- 抓取接口：缓存路径 ----------------
#
# execute_crawl 上有 @cache.memoize(timeout=3600)，"同一平台一小时内只真抓一次"。
# 这条缓存路径以前是坏的（见下面两个用例的说明），而且只在"连打两次"时才现形 ——
# 单次冒烟、手工点一下都看不出来，所以必须有用例钉住。

def test_execute_crawl_returns_plain_dict_not_orm_object(fake_douban, app):
    """execute_crawl 的返回值必须是普通 dict，不能是 ORM 对象。

    这是上面那条缓存路径能正常工作的前提：SimpleCache 存的是对象引用、不做序列化，
    把 CrawlResult 实例塞进去，第二个请求拿到的就是绑在已关闭会话上的对象。
    断言类型比断言行为报警得更早，也别改成 CrawlResult 的子类。
    """
    with app.app_context():
        result = crawler_service.execute_crawl('douban')
    assert type(result) is dict
    assert result['platform'] == 'douban'


def test_crawl_same_platform_twice_hits_cache_and_still_201(client, fake_douban, app):
    """同一平台连打两次：第二次命中缓存，必须还是 201。

    回归用例。原来 execute_crawl 直接 `return rec`，缓存里存下的是 ORM 对象引用，
    第二个请求读它的属性时抛 DetachedInstanceError，接口上就是 500：

        {"error": "Instance <CrawlResult ...> is not bound to a Session;
                   attribute refresh operation cannot proceed"}

    只有"一小时内抓同一个平台两次"才触发，所以肉眼和单次冒烟都发现不了。
    """
    first = client.post('/crawl/douban')
    second = client.post('/crawl/douban')

    assert first.status_code == 201
    assert second.status_code == 201, second.get_data(as_text=True)

    # 命中缓存 = 返回同一个结果：不重新抓、不重复落库、不重复写 CSV
    assert second.get_json() == first.get_json()
    with app.app_context():
        assert CrawlResult.query.count() == 1


# ---------------- 抓取接口：失败分支 ----------------

def test_crawl_unknown_platform_returns_500_json(client):
    resp = client.post('/crawl/nonexistent')
    assert resp.status_code == 500
    assert resp.mimetype == 'application/json'
    assert 'nonexistent' in resp.get_json()['error']


def test_crawl_upstream_failure_returns_500(client, monkeypatch):
    from app.crawlers.douban import DoubanCrawler

    def boom(self):
        raise RuntimeError('上游挂了')

    monkeypatch.setattr(DoubanCrawler, 'fetch_data', boom)
    resp = client.post('/crawl/douban')
    assert resp.status_code == 500
    assert '上游挂了' in resp.get_json()['error']


def test_crawl_commit_failure_rolls_back(client, monkeypatch, fake_douban):
    """写库失败必须 rollback。

    不 rollback 的话坏会话会留在连接上，被后面的请求复用 —— 这类问题在
    "探针过了但接口全挂"的现象里很难查，所以在这里钉住。
    """

    class BoomSession:
        def __init__(self):
            self.rolled_back = False

        def add(self, obj):
            pass

        def commit(self):
            raise RuntimeError('数据库写失败')

        def rollback(self):
            self.rolled_back = True

    session = BoomSession()
    monkeypatch.setattr(crawler_service, 'db', SimpleNamespace(session=session))

    resp = client.post('/crawl/douban')
    assert resp.status_code == 500
    assert '数据库写失败' in resp.get_json()['error']
    assert session.rolled_back is True
