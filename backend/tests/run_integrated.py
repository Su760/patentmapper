"""Run browser → actual API → separate worker → disposable Supabase. No paid calls.

MILESTONE1_DISPOSABLE_SUPABASE=1 python backend/tests/run_integrated.py CONFIG OUTPUT_DIR
CONFIG is local_http_setup.py's test-config.json; OUTPUT_DIR must be new, outside git.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlparse
from uuid import uuid4

import httpx

root = Path(__file__).resolve().parents[2]
config = json.loads(Path(sys.argv[1]).read_text())
out = Path(sys.argv[2]).resolve()
if os.environ.get('MILESTONE1_DISPOSABLE_SUPABASE') != '1':
    raise RuntimeError('Explicit disposable-stack acknowledgement required')
for key in ('API_URL', 'DB_URL'):
    if urlparse(config[key]).hostname not in ('localhost', '127.0.0.1', '::1'):
        raise RuntimeError('Only disposable loopback services are permitted')
if out == root or root in out.parents:
    raise RuntimeError('Keep generated credentials/artifacts outside git')
out.mkdir(mode=0o700, parents=True, exist_ok=False)
api_port = os.environ.get('PM_INTEGRATED_API_PORT', '8019')
api_url = f'http://127.0.0.1:{api_port}/api'
env = {**os.environ, 'PYTHONPATH':str(root/'backend'), 'MOCK_MODE':'true',
       'SUPABASE_URL':config['API_URL'], 'SUPABASE_ANON_KEY':config['ANON_KEY'],
       'SUPABASE_SERVICE_KEY':config['SERVICE_ROLE_KEY'],
       'GROQ_API_KEY':'', 'LENS_API_KEY':'', 'SERPAPI_KEY':'', 'STRIPE_SECRET_KEY':'',
       'PM_INTEGRATED_API_PORT':api_port, 'PM_INTEGRATED_BLOCKED':str(out/'blocked-network'),
       'NEXT_PUBLIC_SUPABASE_URL':config['API_URL'], 'NEXT_PUBLIC_SUPABASE_ANON_KEY':config['ANON_KEY'],
       'NEXT_PUBLIC_API_URL':api_url, 'PM_INTEGRATED_FIXTURE':str(out/'browser.json')}
admin = {'apikey':config['SERVICE_ROLE_KEY'], 'Authorization':f"Bearer {config['SERVICE_ROLE_KEY']}"}
processes, logs, users, sessions = [], [], [], []
try:
    with httpx.Client(base_url=config['API_URL']) as client:
        for _ in range(2):
            email, password = f'release-{uuid4()}@example.test', str(uuid4())
            response = client.post('/auth/v1/admin/users',headers=admin,json={'email':email,'password':password,'email_confirm':True})
            response.raise_for_status(); users.append(response.json()['id'])
            response = client.post('/auth/v1/token?grant_type=password',headers={'apikey':config['ANON_KEY']},json={'email':email,'password':password})
            response.raise_for_status(); sessions.append(response.json())
    fixture = {'api':api_url,'supabase':config['API_URL'],'anon':config['ANON_KEY'],
               'sessions':sessions,'db':config['DB_URL'],'output':str(out)}
    (out/'browser.json').write_text(json.dumps(fixture)); (out/'browser.json').chmod(0o600)
    for kind in ('api','worker'):
        log = (out/f'{kind}.log').open('w'); logs.append(log)
        processes.append(subprocess.Popen([sys.executable,str(root/'backend/tests/integrated_process.py'),kind],cwd=root/'backend',env=env,stdout=log,stderr=log))
    for _ in range(100):
        if any(p.poll() is not None for p in processes):
            raise RuntimeError('API/worker exited; inspect private local process logs')
        try:
            if httpx.get(f'http://127.0.0.1:{api_port}/openapi.json').status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(.1)
    else:
        raise RuntimeError('API startup timed out')
    print(f'Integrated API PID {processes[0].pid}; separate worker PID {processes[1].pid}',flush=True)
    subprocess.run(['npm','run','build'],cwd=root/'frontend',env=env,check=True)
    subprocess.run(['npx','playwright','test','--config','playwright.integrated.config.cjs'],cwd=root/'frontend',env=env,check=True)
    if (out/'blocked-network').exists():
        raise RuntimeError('A non-loopback connection was attempted')
    print('Integrated synthetic flow passed; no non-loopback API/worker connections or paid provider calls. Browser font requests were blocked.',flush=True)
finally:
    for process in processes:
        process.terminate()
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()
    for log in logs:
        log.close()
    with httpx.Client(base_url=config['API_URL']) as client:
        for user in users:
            client.delete(f'/auth/v1/admin/users/{user}',headers=admin).raise_for_status()
