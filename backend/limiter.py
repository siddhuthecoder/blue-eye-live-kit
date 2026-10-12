"""Atomic rolling-window limits shared across every API process."""

import hashlib
import hmac
import math
import time
import uuid
from redis.asyncio import Redis
from .config import Settings

WINDOW_SCRIPT = """
local now = tonumber(ARGV[1])
local member = ARGV[2]
for i, key in ipairs(KEYS) do
  local window = tonumber(ARGV[2*i+1])
  local limit = tonumber(ARGV[2*i+2])
  redis.call('ZREMRANGEBYSCORE', key, '-inf', now-window)
  if redis.call('ZCARD', key) >= limit then
    local first = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    return math.max(1, math.ceil((tonumber(first[2])+window-now)/1000))
  end
end
for i, key in ipairs(KEYS) do
  local window = tonumber(ARGV[2*i+1])
  redis.call('ZADD', key, now, member)
  redis.call('PEXPIRE', key, window+1000)
end
return 0
"""


class RateLimiter:
    def __init__(self, redis: Redis, settings: Settings):
        self.redis = redis
        self.settings = settings

    async def check(self, ip: str) -> int:
        digest = hmac.new(
            self.settings.signing_secret.get_secret_value().encode(), ip.encode(), hashlib.sha256
        ).hexdigest()
        # Same hash tag allows a later migration to Redis Cluster.
        keys = [f"rl:{{enquiries}}:ip:{digest}", "rl:{enquiries}:global"]
        result = await self.redis.eval(
            WINDOW_SCRIPT,
            len(keys),
            *keys,
            int(time.time() * 1000),
            str(uuid.uuid4()),
            600000,
            self.settings.per_ip_limit,
            60000,
            self.settings.global_limit,
        )
        return max(0, math.ceil(int(result)))


def create_redis(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.redis_url.get_secret_value(),
        socket_connect_timeout=2,
        socket_timeout=2,
        max_connections=100,
        decode_responses=True,
        health_check_interval=30,
    )
