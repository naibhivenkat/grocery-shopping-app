import logging
from elasticsearch import Elasticsearch
import datetime
import os

class ElasticsearchHandler(logging.Handler):
    def __init__(self, es_client, index_name="app-logs"):
        logging.Handler.__init__(self)
        self.es = es_client
        self.index = index_name

    def emit(self, record):
        log_entry = self.format(record)
        doc = {
            "@timestamp": datetime.datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "pathname": record.pathname,
            "lineno": record.lineno,
        }
        try:
            self.es.index(index=self.index, document=doc)
        except Exception as e:
            print(f"Failed to send log to Elasticsearch: {e}")
