"""Test bootstrap.

`src/` is put on sys.path explicitly so the tests do not depend on how the
project happens to be installed (the previous suite only worked because the
editable install exposed `agent` by accident).
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
