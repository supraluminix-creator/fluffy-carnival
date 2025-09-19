from prometheus_client import Counter, Summary, start_http_server

REQUEST_LATENCY = Summary('collector_latency_seconds', 'Latency of collector calls', ['collector'])
REQUEST_ERRORS = Counter('collector_errors_total', 'Total errors per collector', ['collector'])
REQUEST_SUCCESS = Counter('collector_success_total', 'Total successes per collector', ['collector'])

def start_metrics_server(port=8000):
    start_http_server(port)