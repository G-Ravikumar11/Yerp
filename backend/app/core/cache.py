"""Heavy read-only panels remembered between visits, until anything is written."""
import time


# Heavy read-only panels are remembered between visits until anything is
# written. Every request that can change data moves this on once it has
# finished, which throws every remembered answer away; a time limit covers
# changes nobody requested (the scheduler, the date rolling over).
_WRITE_VERSION = [0]
_READ_CACHE = {}


def cached_read(key, build, ttl=60):
    now = time.time()
    version = _WRITE_VERSION[0]
    hit = _READ_CACHE.get(key)
    if hit and hit[0] == version and hit[1] > now:
        return hit[2]
    value = build()
    if len(_READ_CACHE) > 2000:
        _READ_CACHE.clear()
    _READ_CACHE[key] = (version, now + ttl, value)
    return value
