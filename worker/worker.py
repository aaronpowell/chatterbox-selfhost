from rq import Worker

from app.redis_conn import get_redis_connection


def main():
    redis_conn = get_redis_connection()
    worker = Worker(["training"], connection=redis_conn)
    worker.work()


if __name__ == "__main__":
    main()
