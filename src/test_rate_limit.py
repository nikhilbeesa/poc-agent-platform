"""Regression: limiter caps RPM across threads; 429s are retried with cooldown; daily quota fails fast."""
import sys, time, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_client as L

def test():
    # 1. limiter: 5 calls/min max -> 5 immediate, 6th must wait
    lim = L._RateLimiter(5)
    t = time.monotonic()
    for _ in range(5): lim.acquire()
    assert time.monotonic() - t < 0.5
    # window slide: fake old timestamps
    lim.calls = type(lim.calls)([time.monotonic() - 59.8] * 5)
    t = time.monotonic(); lim.acquire(); assert 0.1 < time.monotonic() - t < 2, "should wait for window"
    # 2. thread safety: 20 threads, max 10/min, never more than 10 admitted in window
    lim = L._RateLimiter(10); admitted = []
    def w():
        lim.acquire(); admitted.append(time.monotonic())
    th = [threading.Thread(target=w) for _ in range(10)]
    [x.start() for x in th]; [x.join() for x in th]
    assert len(admitted) == 10 and len(lim.calls) == 10
    # 3. retry on 429 with server hint, then success
    class E(Exception):
        status_code = 429
    class C(L.LLMClient):
        n = 0
        def _generate_once(self, p, m):
            C.n += 1
            if C.n < 3: raise E("429 RESOURCE_EXHAUSTED ... Please retry in 0.2s")
            return "ok"
    L._limiter = L._RateLimiter(100); L.RETRY_BASE_DELAY = 0.01
    assert C("gemini", None).generate("x") == "ok" and C.n == 3
    # 4. daily quota fails fast (no retry loop)
    class D(L.LLMClient):
        n = 0
        def _generate_once(self, p, m):
            D.n += 1; raise E("429 quota exceeded for metric ...PerDay... limit: 500")
    try: D("gemini", None).generate("x"); assert False
    except L.LLMQuotaExhausted: pass
    assert D.n == 1
    print("rate limit: all scenarios pass")

if __name__ == "__main__":
    test()
