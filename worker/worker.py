from redis import Redis
from rq import Worker

from app.config import settings


def main():
    redis_conn = Redis.from_url(settings.redis_url)
    worker = Worker(["training"], connection=redis_conn)
    worker.work()


if __name__ == "__main__":
    main()
