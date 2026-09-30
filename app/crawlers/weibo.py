import time

from bs4 import BeautifulSoup

from .base import BaseCrawler


class WeiboCrawler(BaseCrawler):
    def fetch_data(self):
        # 爬取微博热搜（公开页面，合规）
        url = "https://s.weibo.com/top/summary"
        r = self.session.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'lxml')

        res = []
        for item in soup.select('.td-02')[:20]:
            title = item.get_text(strip=True)
            res.append({
                'type': 'weibo',
                'title': title,
                'url': f'https://s.weibo.com{item.a["href"]}' if item.a else ''
            })
        time.sleep(1)
        return res