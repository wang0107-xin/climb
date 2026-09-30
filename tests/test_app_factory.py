"""create_app() 里那段「建表竞态」的兜底。

背景（真事，不是假想）：镜像是 `gunicorn --workers 2`，两个 worker 各自 import
一次 wsgi.py → 两个进程同时对同一个空库跑 `create_all()`。而 create_all 是
「先查表在不在、再 CREATE TABLE」，抢输的那个拿到 `table crawl_result already
exists`；这个异常在 import 期没人接得住，于是 worker 起不来 → gunicorn 判定
"Worker failed to boot" 并让 master 退出（exit code 3）→ 容器被 kubelet 重启。
现象是「每次部署，Pod 都重启 1~2 次」。

下面两条用例钉的是**两个方向** —— 只钉「不崩」是不够的：
兜底一旦写成盲吞，磁盘只读、路径写错这类真问题也会一起被咽下去，
那就退化成"启动失败但看起来正常"。
"""
import sqlite3

import pytest
from sqlalchemy.exc import OperationalError

from app import create_app
from app.extensions import db


def _race_error():
    """抢输的那个 worker 看到的异常 —— 和真实崩溃栈里同形。

    消息刻意写死在这里（而不是从 raise 那儿传进来）：TRY003 要求异常消息
    别散在 raise 语句上。顺带也让"输家"和"真出事"这两种消息各自只有一处定义。
    """
    return OperationalError(
        'CREATE TABLE crawl_result', {},
        sqlite3.OperationalError('table crawl_result already exists'),
    )


def _broken_db_error():
    """真出事那一类：库文件打不开（磁盘只读、路径不对…）。"""
    return OperationalError(
        'CREATE TABLE crawl_result', {},
        sqlite3.OperationalError('unable to open database file'),
    )


def test_create_app_survives_when_another_worker_created_the_tables(app, monkeypatch):
    """抢输了：另一个 worker 已经把表建好 —— create_app() 必须照常返回。

    这里是先真建表、再抛异常，精确复现"输家"的处境：异常是真的，
    但目标（表存在）也已经达成。
    """
    real_create_all = db.create_all

    def racing_create_all():
        real_create_all()
        raise _race_error()

    monkeypatch.setattr(db, 'create_all', racing_create_all)

    assert create_app('production') is not None


def test_create_app_still_raises_when_the_tables_are_really_missing(app, monkeypatch):
    """真出事：表根本没建成 —— 必须照抛，别把真问题也吞了。"""

    def failing_create_all():
        raise _broken_db_error()

    monkeypatch.setattr(db, 'create_all', failing_create_all)
    # 把表删掉，制造"确实没建成"的状态：兜底只在"表已经全在了"时才放过
    with app.app_context():
        db.drop_all()

    with pytest.raises(OperationalError):
        create_app('production')
