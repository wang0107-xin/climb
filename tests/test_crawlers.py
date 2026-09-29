"""爬虫解析层用例。

只测解析，不测网络：把 session.get 换掉，喂固定 HTML 进去。

豆瓣那条注意两点：
  - fetch_data 会循环 10 页、每页 sleep(1)，所以 time.sleep 也要换掉，否则用例白等 10 秒
  - 每页喂的是同一份 HTML，所以断言的是"每页条数 × 页数"，不是真实数据量
"""
import pytest

from app.crawlers.base import BaseCrawler

DOUBAN_HTML = """
<html><body>
<div class="item">
  <a href="https://movie.douban.com/subject/1292052/"><span class="title">肖申克的救赎</span></a>
  <span class="rating_num">9.7</span>
</div>
</body></html>
"""

WEIBO_HTML = """
<html><body><table><tbody>
<tr><td class="td-02"><a href="/weibo?q=%23test%23">测试热搜</a></td></tr>
<tr><td class="td-02">没有链接的那条</td></tr>
</tbody></table></body></html>
"""


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def test_create_unknown_platform_raises_keyerror():
    with pytest.raises(KeyError):
        BaseCrawler.create('nonexistent')


def test_create_returns_crawler_for_platform():
    from app.crawlers.douban import DoubanCrawler

    crawler = BaseCrawler.create('douban')
    assert isinstance(crawler, DoubanCrawler)
    assert crawler.crawl_type == 'default'
    # 没带 UA 会被站点直接挡掉，这条是抓取能不能成功的前提
    assert crawler.session.headers['User-Agent'].startswith('Mozilla/')


def test_douban_parses_title_rating_and_link(monkeypatch):
    crawler = BaseCrawler.create('douban')
    monkeypatch.setattr(crawler.session, 'get', lambda url, **kw: FakeResponse(DOUBAN_HTML))
    monkeypatch.setattr('app.crawlers.douban.time.sleep', lambda s: None)

    rows = crawler.fetch_data()

    assert len(rows) == 10  # range(0, 250, 25) = 10 页，每页喂 1 条
    assert rows[0] == {
        'title': '肖申克的救赎',
        'rating': '9.7',
        'link': 'https://movie.douban.com/subject/1292052/',
    }


def test_weibo_parses_rows_and_tolerates_missing_link(monkeypatch):
    crawler = BaseCrawler.create('weibo')
    monkeypatch.setattr(crawler.session, 'get', lambda url, **kw: FakeResponse(WEIBO_HTML))
    monkeypatch.setattr('app.crawlers.weibo.time.sleep', lambda s: None)

    rows = crawler.fetch_data()

    assert rows[0] == {
        'type': 'weibo',
        'title': '测试热搜',
        'url': 'https://s.weibo.com/weibo?q=%23test%23',
    }
    # 没有 <a> 的那条不能炸，url 退化成空串
    assert rows[1] == {'type': 'weibo', 'title': '没有链接的那条', 'url': ''}
