from ..extensions import db
from datetime import datetime

class CrawlResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(50))
    data = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'platform': self.platform,
            'file_path': self.data.get('path'),
            'count': self.data.get('count'),
            'created_at': self.created_at.isoformat()
        }