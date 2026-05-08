"""Per-adapter pytest conftest.

Puts the adapter's source directory on ``sys.path`` so test modules
in this directory can ``from django_schema import DjangoSchemaParser``
without the adapter being installed as a package.
"""

import sys
from pathlib import Path

ADAPTER_ROOT = Path(__file__).parent.parent
if str(ADAPTER_ROOT) not in sys.path:
    sys.path.insert(0, str(ADAPTER_ROOT))
