import sys
from pathlib import Path

REWIRE = Path(__file__).resolve().parents[1]
REPO = REWIRE.parent
for p in (REWIRE / "explorer_gold", REWIRE / "duct.bdp_conform", REPO / "server"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
