"""Run the portal against the seeded demo database.

Sets its own environment before importing the app so it never touches whatever
the real .env points at. Not used in production - see main.py for that.
"""
import os

# Absolute, so the database found is the same one whichever directory the
# process happens to be launched from.
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(HERE, "demo_portal.db").replace("\\", "/")
os.environ["SECRET_KEY"] = "demo-secret-not-production"
os.environ["COOKIE_SECURE"] = "false"
os.environ["SCHEDULER_ENABLED"] = "0"

import sys

sys.path.insert(0, HERE)

import uvicorn

if __name__ == "__main__":
    # reload so a code change is picked up without restarting by hand.
    uvicorn.run("main:app", host="127.0.0.1", port=8931, log_level="warning",
                reload=True, reload_dirs=[HERE])
