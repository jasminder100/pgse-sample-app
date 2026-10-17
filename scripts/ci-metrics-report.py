#!/usr/bin/env python3
"""PGSE CI metrics report (deliverable 7).

Downloads the `ci-metrics` artifact from recent ci-gate runs and reports:
  - pass/fail ratio and latency (avg, p95) per tool
  - violations by rule (gator) and by check (Checkov)
  - a per-day trend of runs, failures and violations
Writes <prefix>.json (summary) and <prefix>-trend.csv (for spreadsheets/Grafana).
Requires the GitHub CLI (`gh`), logged in.
"""
import argparse, collections, csv, json, pathlib, subprocess, sys, tempfile


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def p95(values):
    s = sorted(values)
    return s[int(0.95 * (len(s) - 1))] if s else 0


ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument("--repo", default="jasminder100/pgse-sample-app")
ap.add_argument("--limit", type=int, default=50, help="how many recent ci-gate runs to scan")
ap.add_argument("-o", "--output", default="ci-metrics-report", help="output file prefix")
args = ap.parse_args()

res = gh("run", "list", "-R", args.repo, "--workflow", "ci-gate.yaml", "--limit", str(args.limit),
         "--json", "databaseId,createdAt,event,headBranch,conclusion")
if res.returncode != 0:
    sys.exit(f"gh run list failed: {res.stderr.strip()}")
runs = json.loads(res.stdout)

records = []
with tempfile.TemporaryDirectory() as tmp:
    for r in runs:
        d = pathlib.Path(tmp) / str(r["databaseId"])
        dl = gh("run", "download", str(r["databaseId"]), "-R", args.repo, "-n", "ci-metrics", "-D", str(d))
        f = d / "ci-metrics.json"
        if dl.returncode != 0 or not f.exists():
            continue  # older runs (before metrics existed) have no artifact
        m = json.loads(f.read_text())
        m["createdAt"], m["branch"] = r["createdAt"], r["headBranch"]
        records.append(m)

if not records:
    sys.exit("No ci-gate runs with a ci-metrics artifact found yet.")

# --- per-tool pass/fail and latency ---
by_tool = collections.defaultdict(list)
for m in records:
    for t in m["tools"]:
        by_tool[t["tool"]].append(t)

tools = {}
for name, ts in sorted(by_tool.items()):
    durs = [t["durationMs"] for t in ts]
    passed = sum(1 for t in ts if t["passed"])
    tools[name] = {
        "runs": len(ts), "passed": passed, "failed": len(ts) - passed,
        "passRatePercent": round(100 * passed / len(ts), 1),
        "avgDurationMs": round(sum(durs) / len(durs)), "p95DurationMs": p95(durs),
    }

# --- which rules / checks fail most ---
by_rule, by_check = collections.Counter(), collections.Counter()
for m in records:
    for t in m["tools"]:
        by_rule.update(t.get("byRule", {}))
        by_check.update(t.get("byCheck", {}))

# --- trend per day ---
trend = collections.OrderedDict()
for m in sorted(records, key=lambda x: x["createdAt"]):
    day = m["createdAt"][:10]
    row = trend.setdefault(day, {"date": day, "runs": 0, "failedRuns": 0, "gatorViolations": 0, "checkovViolations": 0})
    row["runs"] += 1
    if any(not t["passed"] for t in m["tools"]):
        row["failedRuns"] += 1
    for t in m["tools"]:
        row[f'{t["tool"]}Violations'] = row.get(f'{t["tool"]}Violations', 0) + t["violations"]

# --- print a readable report ---
print(f"PGSE CI metrics: {len(records)} runs with metrics (scanned {len(runs)} ci-gate runs)\n")
print(f"{'tool':<10}{'runs':>6}{'pass%':>8}{'avg ms':>9}{'p95 ms':>9}")
for name, s in tools.items():
    print(f"{name:<10}{s['runs']:>6}{s['passRatePercent']:>8}{s['avgDurationMs']:>9}{s['p95DurationMs']:>9}")
print("\nMost-violated rules (gator):  " + (", ".join(f"{k}={v}" for k, v in by_rule.most_common()) or "none"))
print("Most-failed checks (Checkov): " + (", ".join(f"{k}={v}" for k, v in by_check.most_common()) or "none"))
print(f"\n{'date':<12}{'runs':>6}{'failed':>8}{'gator viol':>12}{'checkov viol':>14}")
for r in trend.values():
    print(f"{r['date']:<12}{r['runs']:>6}{r['failedRuns']:>8}{r['gatorViolations']:>12}{r['checkovViolations']:>14}")

summary = {"runsWithMetrics": len(records), "tools": tools,
           "violationsByRule": dict(by_rule.most_common()), "failuresByCheck": dict(by_check.most_common()),
           "trend": list(trend.values())}
pathlib.Path(f"{args.output}.json").write_text(json.dumps(summary, indent=2))
with open(f"{args.output}-trend.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["date", "runs", "failedRuns", "gatorViolations", "checkovViolations"])
    w.writeheader()
    w.writerows(trend.values())
print(f"\nWrote {args.output}.json and {args.output}-trend.csv")
