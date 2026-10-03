"""Prepare ONLY a disposable local CLI project. Never links a hosted project.

python supabase/tests/local_http_setup.py /tmp/patentmapper-m1-http
Starts local Docker services; writes generated test credentials outside the repo.
"""
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
target = Path(sys.argv[1]).resolve()
if target.exists():
    raise SystemExit("Choose a new empty temporary directory (refusing to modify an existing project)")
target.mkdir(parents=True)
cli = ["npx", "--yes", "supabase@2.119.0"]
subprocess.run(cli + ["init", "--workdir", str(target)], check=True)
config = target / "supabase/config.toml"
text = config.read_text().replace('enable_anonymous_sign_ins = false', 'enable_anonymous_sign_ins = true')
text = text.replace('anonymous_users = 30', 'anonymous_users = 1000')
config.write_text(text)
excluded = "realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor"
# CLI start/status include test credentials: keep output private and out of CI logs.
with (target / "start.log").open("w") as log:
    subprocess.run(cli + ["start", "--workdir", str(target), "-x", excluded], stdout=log, stderr=log, check=True)
status = subprocess.run(cli + ["status", "--workdir", str(target), "-o", "json"], capture_output=True, text=True, check=True)
data = json.loads(status.stdout)
credentials = target / "test-config.json"
credentials.write_text(json.dumps(data))
credentials.chmod(0o600)
for path in sorted((root / "supabase/migrations").glob("*.sql")):
    subprocess.run(["psql", "-X", "-v", "ON_ERROR_STOP=1", data["DB_URL"], "-f", str(path)], check=True, capture_output=True)
subprocess.run(["psql", "-X", data["DB_URL"], "-c", "NOTIFY pgrst, 'reload schema'"], check=True, capture_output=True)
print(f"Disposable Supabase ready. MILESTONE1_SUPABASE_CONFIG={credentials}")
