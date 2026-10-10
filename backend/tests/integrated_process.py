"""Test-only process launcher: real API/worker, loopback network only."""
import ipaddress
import os
from pathlib import Path
import runpy
import sys


def audit(event, args):
    if event != 'socket.connect':
        return
    address = args[1]
    if isinstance(address, tuple):
        try:
            allowed = ipaddress.ip_address(address[0]).is_loopback
        except ValueError:
            allowed = False
        if not allowed:
            Path(os.environ['PM_INTEGRATED_BLOCKED']).write_text('Non-loopback connection attempted\n')
            raise RuntimeError('Integrated tests forbid non-loopback connections')


sys.addaudithook(audit)
if os.environ.get('MOCK_MODE') != 'true':
    raise RuntimeError('Synthetic integration requires MOCK_MODE=true')
if sys.argv[1] == 'worker':
    runpy.run_module('app.worker', run_name='__main__')
else:
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=int(os.environ['PM_INTEGRATED_API_PORT']))
