from abc import ABC, abstractmethod

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class BaseCrawler(ABC):
    def __init__(self, crawl_type='default'):
        self.crawl_type = crawl_type
        self._init_session()

    def _init_session(self):
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.3)
        self.session.mount('https://', HTTPAdapter(max_retries=retry))
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9'
        })

    @classmethod
    def create(cls, platform: str, crawl_type: str = 'default'):
        from . import douban, weibo
        crawlers = {
            'douban': douban.DoubanCrawler,
            'weibo': weibo.WeiboCrawler
        }
        return crawlers[platform](crawl_type)

    @abstractmethod
    def fetch_data(self):
        pass