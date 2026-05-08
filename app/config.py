import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret')
    JSON_AS_ASCII = False
    ENV = os.getenv('FLASK_ENV')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
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