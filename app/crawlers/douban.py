from .base import BaseCrawler
from bs4 import BeautifulSoup
import time

class DoubanCrawler(BaseCrawler):
    def fetch_data(self):
        movies = []
        for start in range(0, 250, 25):
            url = f'https://movie.douban.com/top250?start={start}'
            r = self.session.get(url)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'lxml')
            for item in soup.select('.item'):
                movies.append({
                    'title': item.select_one('.title').text.strip(),
                    'rating': item.select_one('.rating_num').text.strip(),
                    'link': item.select_one('a')['href']
                })
            time.sleep(1)
        return movies