"""For tests that load the compiled React app. It is built by `npm run build` in frontend/ and not committed,
so these tests skip, rather than fail, on a machine that has not built it."""
import os

import pytest

FRONTEND_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "dist")

needs_frontend_build = pytest.mark.skipif(
    not os.path.isfile(os.path.join(FRONTEND_DIST, "index.html")),
    reason="the React app is not built: run `npm run build` in frontend/")
