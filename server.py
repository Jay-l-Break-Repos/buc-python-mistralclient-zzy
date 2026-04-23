"""
Entry point for the Workflow API server.

Run directly with::

    python server.py

Or via a WSGI server::

    gunicorn server:app
"""

from app.factory import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9090, debug=False)
