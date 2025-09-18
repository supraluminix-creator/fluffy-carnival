# Base collector class for all collectors
class BaseCollector:
    def collect(self, conn):
        raise NotImplementedError()
