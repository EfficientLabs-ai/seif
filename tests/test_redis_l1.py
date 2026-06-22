"""L1 Redis-backend integration test for WorkingMemory.

Skips cleanly when the redis client or a reachable Redis server is absent (so CI / the stdlib-python suite
stays green), and exercises the real Redis backend when one is provisioned (the dedicated seif-redis
container + ~/.config/seif/redis.url, or $SEIF_REDIS_URL)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
import tripartite as T  # noqa: E402


def _redis_url():
    return os.environ.get("SEIF_REDIS_URL") or T._configured_redis_url() or "redis://127.0.0.1:6379/0"


def _redis_available():
    try:
        import redis  # noqa: F401
        c = redis.Redis.from_url(_redis_url(), socket_connect_timeout=0.5, decode_responses=True)
        c.ping()
        return True
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_redis_available(), "no redis client/server reachable — L1 falls back to file (tested elsewhere)")
class RedisL1Test(unittest.TestCase):
    def setUp(self):
        # isolated namespace per test run so we never collide with live data
        self.ns = f"seif_test_{os.getpid()}"
        self.wm = T.WorkingMemory(namespace=self.ns, redis_url=_redis_url())
        self.assertEqual(self.wm.backend, "redis", "this test requires the redis backend")

    def tearDown(self):
        for k in self.wm.keys():
            self.wm.delete(k)

    def test_set_get_delete_roundtrip(self):
        self.wm.set("k", {"a": 1})
        self.assertEqual(self.wm.get("k"), {"a": 1})
        self.wm.delete("k")
        self.assertIsNone(self.wm.get("k"))

    def test_ttl_expiry(self):
        self.wm.set("e", 1, ttl=1)
        self.assertEqual(self.wm.get("e"), 1)        # present within ttl

    def test_keys_prefix_and_namespace_strip(self):
        self.wm.set("a", 1); self.wm.set("ab", 2); self.wm.set("zz", 3)
        self.assertEqual(self.wm.keys("a"), ["a", "ab"])   # keys() strips the namespace

    def test_namespace_isolation(self):
        other = T.WorkingMemory(namespace=self.ns + "_other", redis_url=_redis_url())
        try:
            self.wm.set("dup", "mine"); other.set("dup", "theirs")
            self.assertEqual(self.wm.get("dup"), "mine")
            self.assertEqual(other.get("dup"), "theirs")
        finally:
            for k in other.keys():
                other.delete(k)

    def test_default_on_missing(self):
        self.assertEqual(self.wm.get("nope", 42), 42)


if __name__ == "__main__":
    unittest.main()
