"""Fan jobs out over a pool of GPU endpoints.

One worker thread per endpoint pulls the next job from a shared queue, so fast
nodes take more work and a slow or dead node can't hold the film hostage.
Failed jobs are retried on whichever node is free next. Every attempt is logged
to a timeline so we can plot node utilisation and compute the real speedup.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    key: str
    run: Callable[[str], Any]   # called with the endpoint URL
    attempts: int = 0


@dataclass
class Event:
    job: str
    endpoint: str
    start: float
    end: float
    ok: bool
    error: str = ""


@dataclass
class RunResult:
    results: dict[str, Any] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
    timeline: list[Event] = field(default_factory=list)
    wall_seconds: float = 0.0

    @property
    def busy_seconds(self) -> float:
        return sum(e.end - e.start for e in self.timeline)


def run_pool(
    jobs: list[Job],
    endpoints: list[str],
    max_attempts: int = 3,
    max_consecutive_failures: int = 2,
    log: Callable[[str], None] = print,
) -> RunResult:
    if not endpoints:
        raise ValueError("no endpoints")
    q: queue.Queue[Job] = queue.Queue()
    for j in jobs:
        q.put(j)
    out = RunResult()
    lock = threading.Lock()
    remaining = [len(jobs)]
    t0 = time.time()

    def worker(ep: str):
        fails = 0
        while True:
            with lock:
                if remaining[0] == 0:
                    return
            try:
                job = q.get(timeout=0.2)
            except queue.Empty:
                continue
            job.attempts += 1
            start = time.time()
            try:
                res = job.run(ep)
                ev = Event(job.key, ep, start - t0, time.time() - t0, True)
                with lock:
                    out.results[job.key] = res
                    out.timeline.append(ev)
                    remaining[0] -= 1
                log(f"[ok]   {job.key} on {ep} in {ev.end - ev.start:.1f}s")
                fails = 0
            except Exception as e:  # noqa: BLE001 - any node error is retryable
                ev = Event(job.key, ep, start - t0, time.time() - t0, False, repr(e))
                with lock:
                    out.timeline.append(ev)
                fails += 1
                if job.attempts < max_attempts:
                    log(f"[retry] {job.key} failed on {ep}: {e!r}")
                    q.put(job)
                else:
                    with lock:
                        out.failed[job.key] = repr(e)
                        remaining[0] -= 1
                    log(f"[fail] {job.key}: {e!r}")
                if fails >= max_consecutive_failures:
                    log(f"[drop] endpoint {ep} after {fails} consecutive failures")
                    return

    threads = [threading.Thread(target=worker, args=(ep,), daemon=True) for ep in endpoints]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # If every endpoint dropped out, whatever is left in the queue failed.
    while not q.empty():
        j = q.get()
        out.failed.setdefault(j.key, "no healthy endpoints left")
    out.wall_seconds = time.time() - t0
    return out
