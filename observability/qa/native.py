import os
import json
import subprocess
import sys
import pathlib

c = json.load(open("/opt/config.json"))
t = next(x for x in [*c["postgres"], c["redis"]] if x["service"] == sys.argv[1])
env = dict(os.environ)
pg = "database" in t
env.update(
    {
        "HOSTNAME": t["host"],
        "PORT": str(t["port"]),
        "USERNAME": t["username"],
        "PASSWORD": pathlib.Path(t["passwordFile"]).read_text().strip(),
        "METRICS": "true",
        "INVENTORY": "false",
    }
)
if pg:
    env.update(
        {
            "DATABASE": t["database"],
            "COLLECTION_LIST": json.dumps({t["database"]: {}}),
            "COLLECT_BLOAT_METRICS": "false",
            "COLLECT_DB_LOCK_METRICS": "false",
            "ENABLE_QUERY_MONITORING": "false",
            "TIMEOUT": "3",
            "CUSTOM_METRICS_QUERY": "SELECT 'blocked_sessions' AS metric_name, 'gauge' AS metric_type, count(*) AS metric_value FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'",
        }
    )
else:
    env.update({"REMOTE_MONITORING": "true", "CONFIG_INVENTORY": "false", "KEYS": "{}"})
r = subprocess.run(
    ["nri-postgresql" if pg else "nri-redis"],
    env=env,
    capture_output=True,
    text=True,
    timeout=20,
)
if r.returncode:
    print("Integration did not collect", file=sys.stderr)
    raise SystemExit(1)
print(r.stdout)
