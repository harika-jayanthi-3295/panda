"""
Day 5 – Fleet
Teaches : embarrassingly parallel agent execution using stdlib only.
Design  : ThreadPoolExecutor submits one job per thread; futures are collected
          in input order so the caller can zip(jobs, results) without sorting;
          exceptions are caught per-job and turned into error reports so one
          bad job never kills the whole fleet.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed


def run_fleet(jobs: list[dict], make_harness, max_workers: int = 4) -> list[dict]:
    """Run a list of jobs in parallel and return results in input order.

    Each job dict must have: name (str), workdir (str), task (str).
    make_harness(workdir) must return a Harness ready to call .run(task).

    Returns a list of result dicts in the same order as jobs:
      success → {"name": ..., "ok": True,  "report": final_text}
      failure → {"name": ..., "ok": False, "report": "<ExcType>: <message>"}
    """
    results: dict[int, dict] = {}

    def _run_one(index: int, job: dict) -> tuple[int, dict]:
        try:
            h      = make_harness(job["workdir"])
            report = h.run(job["task"])
            return index, {"name": job["name"], "ok": True, "report": report}
        except Exception as exc:
            return index, {"name": job["name"], "ok": False,
                           "report": f"{type(exc).__name__}: {exc}"}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_one, i, job): i for i, job in enumerate(jobs)}
        for fut in as_completed(futures):
            idx, result = fut.result()
            results[idx] = result

    return [results[i] for i in range(len(jobs))]
