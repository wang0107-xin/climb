"""模型层用例：结果序列化。

CrawlResult.to_dict() 是抓取接口对外的唯一出口形状，字段名一改调用方就坏，
所以字段集合、字段类型在这里钉死。
"""
from datetime import datetime

import pytest

from app.extensions import db
from app.models.result import CrawlResult


def _save_and_serialize(app, **kwargs):
    """写入并序列化。

    必须在 app_context 里调用 to_dict()：commit 之后实例属性就过期了
    （SQLAlchemy 的 expire_on_commit 默认是开的），出了上下文再访问会 DetachedInstanceError。
    """
    with app.app_context():
        rec = CrawlResult(**kwargs)
        db.session.add(rec)
        db.session.commit()
        return rec.to_dict()


def test_to_dict_returns_exactly_the_contract_fields(app):
    body = _save_and_serialize(
        app, platform='weibo', data={'count': 3, 'path': 'data/weibo_20260101_0000.csv'}
    )
    assert set(body) == {'id', 'platform', 'file_path', 'count', 'created_at'}


def test_to_dict_maps_data_json_to_flat_fields(app):
    body = _save_and_serialize(
        app, platform='douban', data={'count': 100, 'path': 'data/douban_20260101_0000.csv'}
    )
    assert body['platform'] == 'douban'
    assert body['count'] == 100
    assert body['file_path'] == 'data/douban_20260101_0000.csv'
    assert isinstance(body['id'], int)


def test_to_dict_created_at_is_isoformat(app):
    body = _save_and_serialize(app, platform='douban', data={'count': 1, 'path': 'data/x.csv'})
    # 能被 fromisoformat 解回来，才算真的是 ISO 格式，而不是随便一个字符串
    parsed = datetime.fromisoformat(body['created_at'])
    assert parsed.year >= 2024


def test_data_json_round_trips(app):
    with app.app_context():
        rec = CrawlResult(platform='douban', data={'count': 2, 'path': 'data/x.csv'})
        db.session.add(rec)
        db.session.commit()
        rec_id = rec.id

    with app.app_context():
        again = db.session.get(CrawlResult, rec_id)
        assert again.data == {'count': 2, 'path': 'data/x.csv'}


def test_to_dict_with_null_data_currently_raises(app):
    """记录一个已知问题（characterization test，不是在说这样对）。

    data 列为 NULL 时 to_dict() 会 AttributeError（接口上就是 500）。
    现在还不会有代码路径把 data 写成 NULL，所以先按现状钉住；
    哪天真要放开，把 to_dict 里的 self.data.get 改成带兜底的取值，
    这个用例会失败 —— 那时候把它一起改掉就对了。
    """
    with app.app_context():
        rec = CrawlResult(platform='douban', data=None)
        db.session.add(rec)
        db.session.commit()
        with pytest.raises(AttributeError):
            rec.to_dict()
