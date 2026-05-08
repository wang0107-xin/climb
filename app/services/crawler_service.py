import csv
from datetime import datetime
from pathlib import Path
from ..extensions import db, cache
from ..models.result import CrawlResult
from ..crawlers.base import BaseCrawler

BASE = Path(__file__).parent.parent.parent
DATA_DIR = BASE / 'data'
DATA_DIR.mkdir(exist_ok=True)

def save_to_csv(data, prefix):
    fname = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    path = DATA_DIR / fname
    with open(path, 'w', encoding='utf-8', newline='') as f:
        if data:
            w = csv.DictWriter(f, fieldnames=data[0].keys())
            w.writeheader()
            w.writerows(data)
    return str(path.relative_to(BASE))

@cache.memoize(timeout=3600)
def execute_crawl(platform: str):
    try:
        crawler = BaseCrawler.create(platform)
        data = crawler.fetch_data()
        csv_path = save_to_csv(data, platform)
        rec = CrawlResult(
            platform=platform,
            data={'count': len(data), 'path': csv_path}
        )
        db.session.add(rec)
        db.session.commit()
        return rec
    except Exception as e:
        db.session.rollback()
        raise e