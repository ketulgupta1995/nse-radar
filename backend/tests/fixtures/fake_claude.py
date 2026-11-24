"""Stand-in for the `claude` command in tests. Modes via FAKE_CLAUDE_MODE: fail | slow | env."""

import json
import os
import sys
import time

mode = os.environ.get("FAKE_CLAUDE_MODE", "")
if "--version" in sys.argv:
    print("9.9.9 (fake)")
    sys.exit(0)
prompt = sys.stdin.read()
if mode == "fail":
    sys.stderr.write("boom: fake failure\n")
    sys.exit(3)
if mode == "slow":
    time.sleep(30)
if mode == "env":
    print(json.dumps({"result": json.dumps(dict(os.environ))}))
else:
    print(json.dumps({"result": "echo: " + prompt[:20]}))
