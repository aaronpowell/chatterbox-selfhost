from redis import Redis
from rq import Connection, Worker

from app.config import settings


def main():
    redis_conn = Redis.from_url(settings.redis_url)
    with Connection(redis_conn):
        worker = Worker(["training"])
        worker.work()


if __name__ == "__main__":
    main()

