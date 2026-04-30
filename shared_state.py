"""Shared mutable state between main.py and API routes.

Why this module exists:
    When main.py runs as ``__main__``, its module-level globals live in the
    ``__main__`` namespace.  Importing ``from main import ...`` in routes.py
    creates a *separate* ``main`` module namespace, so mutations to the dict
    in one are invisible to the other.  Putting the shared dict here avoids
    that classic Python gotcha.
"""

# Global scrape status -- shared between background thread and web server.
# This lets the dashboard show "Scraping in progress..." before the first
# scrape completes, instead of showing an empty page.
initial_scrape_status: dict = {
    "in_progress": False,
    "message": "",
    "progress": 0,
    "completed": False,
}
