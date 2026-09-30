import os
from typing import ClassVar

from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret')
    JSON_AS_ASCII = False
    ENV = os.getenv('FLASK_ENV')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # ClassVar：这是个**类级别**的配置字典，所有实例共用一份，没人会去改它。
    # 不标注的话 ruff 的 RUF012 会把它当成"可变默认值"—— 那是 dataclass 那类场景里的
    # 真陷阱（多个实例共享同一个 list/dict）。标注成 ClassVar 就是明确告诉类型检查器和
    # lint："我知道它是共享的，这是有意的。"
    # 对运行时零影响：ClassVar 只是注解，Flask 的 from_object 照样能按大写名读到它。
    SQLALCHEMY_ENGINE_OPTIONS: ClassVar[dict] = {
        'pool_size': 10,
        'pool_recycle': 300,
        'pool_pre_ping': True
    }

class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = True
    SQLALCHEMY_ECHO = True

class ProductionConfig(Config):
    DEBUG = False
    PROPAGATE_EXCEPTIONS = True

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig
}