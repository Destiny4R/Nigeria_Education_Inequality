"""gunicorn settings (run from the project root: gunicorn -c deploy/gunicorn.conf.py eduineq.wsgi)."""
import multiprocessing

bind = "unix:/run/eduineq/gunicorn.sock"          # nginx proxies to this socket
workers = max(2, min(4, multiprocessing.cpu_count()))
threads = 4                                        # analyses run in threads when ANALYSIS_EXECUTION=thread
timeout = 300                                      # the full causal analysis takes about one minute; simulations seconds
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = "127.0.0.1"
