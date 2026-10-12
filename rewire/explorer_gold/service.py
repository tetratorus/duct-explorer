"""Start the DUCT Explorer service in spine mode, without editing upstream code.

    EXPLORER_SPINE_URL=http://127.0.0.1:8000 python rewire/explorer_gold/service.py service [explorer CLI args]

Same CLI as `explorer` (server/explorer/cli.py). The only difference is that the server instance is
SpineGoldExplorerServer, so the extra /spine/* endpoints are available. Without EXPLORER_SPINE_URL, use the normal
`explorer` command: analyses then run DUCT processors directly, as before.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "server")]

import explorer.cli  # noqa: E402
from server_ext import SPINE_URL_ENV, SpineGoldExplorerServer  # noqa: E402

if __name__ == "__main__":
    if not os.environ.get(SPINE_URL_ENV):
        sys.exit(f"set {SPINE_URL_ENV} to the spine serve base URL")
    explorer.cli.ExplorerServer = SpineGoldExplorerServer
    explorer.cli.main()
