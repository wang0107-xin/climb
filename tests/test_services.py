"""服务层用例：CSV 落盘。

BASE / DATA_DIR 已经被 conftest 的 _isolate 夹具改到用例自己的临时目录，
所以这里直接调用就行，产物不会落进项目的 data/。
"""
from app.services.crawler_service import save_to_csv


def test_save_to_csv_writes_header_and_rows(tmp_path):
    rel = save_to_csv([{'title': 'a', 'rating': '9.0'}, {'title': 'b', 'rating': '8.0'}], 'douban')

    assert rel.startswith('data/')
    assert rel.endswith('.csv')

    lines = (tmp_path / rel).read_text(encoding='utf-8').splitlines()
    assert lines[0] == 'title,rating'
    assert lines[1] == 'a,9.0'
    assert len(lines) == 3


def test_save_to_csv_with_empty_data_creates_empty_file(tmp_path):
    """记录一个已知行为：抓空的时候会落一个 0 字节文件（连表头都没有）。

    如果以后希望空结果也带表头（下游读 CSV 时更省事），
    改 save_to_csv 里的 `if data:` 分支，这个用例会失败并提醒你。
    """
    rel = save_to_csv([], 'douban')

    path = tmp_path / rel
    assert path.exists()
    assert path.read_text(encoding='utf-8') == ''
