"""Version-bound first-use latency sample for the public Merismos sandbox (X1 slice).

It does only what every anonymous visitor does: it loads the page and its script,
creates an isolated sandbox session (24 h expiry), reads the sandbox workspace and
runs the scripted sandbox planner on offer-4471, which never calls a model. No live
mode, no approval, no publication.

Each request opens a fresh TLS connection, which a browser would reuse, so API
steps are upper bounds. No cold or warm classification is attempted: whole-request
time is not Lambda start-up time.

Usage: python docs/measurements/sandbox_latency.py [samples=10] [spacing_seconds=15]
"""
import datetime
import json
import pathlib
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "https://d2qnkmlhs7y5fp.cloudfront.net"
OUT = pathlib.Path(__file__).parent


def call(method, path, body=None, headers=None, timeout=40):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(BASE + path, data=data, method=method, headers={
        "Content-Type": "application/json", "User-Agent": "merismos-x1-latency",
        "Cache-Control": "no-cache", **(headers or {})})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload, status, got = response.read(), response.status, response.headers
    except urllib.error.HTTPError as error:
        payload, status, got = error.read(), error.code, error.headers
    except Exception as error:  # timeout, reset, DNS: recorded, never dropped
        return {"ms": round((time.perf_counter() - start) * 1000), "status": None,
                "error": type(error).__name__, "bytes": 0, "json": None, "lambda_request": None}
    elapsed = round((time.perf_counter() - start) * 1000)
    try:
        parsed = json.loads(payload)
    except ValueError:
        parsed = None
    return {"ms": elapsed, "status": status, "bytes": len(payload), "json": parsed,
            "text": payload.decode("utf-8", "replace") if parsed is None else None,
            "lambda_request": got.get("X-Merismos-Lambda-Request-Id")}


def offer_status(workspace, offer_id):
    for row in (workspace or {}).get("offers", []):
        if row.get("id") == offer_id or (row.get("offer") or {}).get("id") == offer_id:
            return row.get("status")
    return None


def summary(values):
    if not values:
        return {"n": 0}
    return {"n": len(values), "min": min(values), "median": round(statistics.median(values)),
            "max": max(values)}


def main():
    samples = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    spacing = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
    started = datetime.datetime.now(datetime.timezone.utc)
    release = call("GET", "/release.json")
    backend = call("GET", "/api/version")
    page = call("GET", "/")
    script = re.search(r'src="/?(assets/[^"]+\.js)"', page.get("text") or "")
    bundle = call("GET", "/" + script.group(1)) if script else {"ms": None, "status": None}
    rows = []
    for index in range(samples):
        row = {"sample": index + 1, "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        session = call("POST", "/api/sessions", {})
        row["session"] = {k: session[k] for k in ("ms", "status", "lambda_request")}
        handle = (session["json"] or {}).get("session")
        if not handle:
            row["failure"] = f"session status {session['status']} {session.get('error', '')}"
            rows.append(row)
            continue
        workspace = call("GET", "/api/workspace?mode=sandbox",
                         headers={"X-Merismos-Session": handle})
        row["workspace"] = {k: workspace[k] for k in ("ms", "status", "lambda_request")}
        version = (workspace["json"] or {}).get("version")
        run = call("POST", "/api/offers/offer-4471/run",
                   {"mode": "sandbox", "version": version, "request_id": uuid.uuid4().hex},
                   headers={"X-Merismos-Session": handle})
        row["run"] = {k: run[k] for k in ("ms", "status", "lambda_request")}
        row["run"]["offer_status_after"] = offer_status(run["json"], "offer-4471")
        if run["status"] != 200:
            row["failure"] = f"run status {run['status']} {run.get('error', '')} {str(run['json'])[:160]}"
        rows.append(row)
        if index + 1 < samples:
            time.sleep(spacing)

    def ok(step):
        return [r[step]["ms"] for r in rows if step in r and r[step]["status"] in (200, 201)]

    report = {
        "started_utc": started.isoformat(), "samples": samples, "spacing_seconds": spacing,
        "client": "python urllib, one TLS connection per request, from the owner's workstation",
        "served_frontend_commit": (release["json"] or {}).get("commit"),
        "backend_version": backend["json"],
        "page": {"html_ms": page["ms"], "html_status": page["status"], "html_bytes": page["bytes"],
                 "script": script.group(1) if script else None, "script_ms": bundle["ms"],
                 "script_status": bundle["status"], "script_bytes": bundle.get("bytes")},
        "steps": {step: summary(ok(step)) for step in ("session", "workspace", "run")},
        "failures": [r for r in rows if "failure" in r],
        "rows": rows,
    }
    name = OUT / f"x1-latency-{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    name.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("saved", name)
    print("frontend", report["served_frontend_commit"], "| backend",
          (report["backend_version"] or {}).get("commit"))
    print("page:", report["page"])
    print("| step | n ok | min ms | median ms | max ms |")
    print("|---|---|---|---|---|")
    for step, values in report["steps"].items():
        print(f"| {step} | {values.get('n')} | {values.get('min')} | {values.get('median')} | {values.get('max')} |")
    print("failures:", len(report["failures"]))
    print("offer-4471 status after run:", sorted({str(r.get('run', {}).get('offer_status_after')) for r in rows}))


if __name__ == "__main__":
    main()
