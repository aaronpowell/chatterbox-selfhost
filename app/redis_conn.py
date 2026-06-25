from redis import Redis

from app.config import settings


def get_redis_connection() -> Redis:
    """Create a Redis connection from settings.

    Aspire serves Redis over TLS (``rediss://``) using a per-resource, self-signed
    development certificate. Python's SSL stack verifies against its own CA bundle
    (certifi) and therefore can't validate that cert, so we relax verification for
    TLS connections in this self-hosted/dev setup. Plain ``redis://`` URLs are used
    as-is.
    """
    url = settings.redis_url
    if url.startswith("rediss://"):
        return Redis.from_url(url, ssl_cert_reqs=None)
    return Redis.from_url(url)
