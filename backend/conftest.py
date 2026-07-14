"""Make `backend/` importable regardless of where pytest is launched from, so tests
can `import etl...` / `import app...` exactly as the ETL modules do at runtime
(each script also does `sys.path.append(.../backend)`; this mirrors it for collection)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
