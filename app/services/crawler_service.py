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
    # as_posix()：这个字符串会被写进 CrawlResult.data，再由 to_dict() 暴露成
    # 接口的 file_path 字段。用默认的 str() 在 Windows 上会得到 'data\\x.csv'，
    # 在容器里得到 'data/x.csv'，同一个字段两种形状。统一成正斜杠。
    return path.relative_to(BASE).as_posix()

@cache.memoize(timeout=3600)
def execute_crawl(platform: str):
    """抓一次、落库、返回拍平后的 dict —— 不是 CrawlResult 实例。

    这里返回 dict 而不是 ORM 对象是有原因的，别改回去：
    memoize 缓存的是函数的返回值，而 SimpleCache 就是个内存字典、存的是**对象引用**
    （不做序列化）。ORM 对象绑在产生它的那个请求的数据库会话上，会话在请求结束时就关了。
    于是"一小时内第二次抓同一个平台"拿到的会是绑在已关闭会话上的实例，
    一读属性就 DetachedInstanceError，接口上表现为 500。
    返回 dict 就没这个问题：它自包含，不需要再碰数据库。

    缓存的语义是"同一个平台一小时内只真抓一次"：命中缓存时不会再落库、也不会再写 CSV。
    """
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
        # 必须在 app_context 里拍平：commit 之后属性已过期，出了上下文就读不到了
        return rec.to_dict()
    except Exception as e:
        db.session.rollback()
        raise e