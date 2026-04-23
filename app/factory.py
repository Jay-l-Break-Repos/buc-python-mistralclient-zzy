"""
Flask application factory.

Usage
-----
::

    from app.factory import create_app
    app = create_app()
    app.run()
"""

from flask import Flask

from app.api.workflows.routes import workflows_bp


def create_app(config: dict | None = None) -> Flask:
    """
    Create and configure the Flask application.

    Parameters
    ----------
    config:
        Optional dictionary of configuration values that override the
        defaults.  Useful for injecting test-specific settings (e.g. a
        temporary storage directory).

    Returns
    -------
    Flask
        A fully configured Flask application instance.
    """
    app = Flask(__name__)

    # ------------------------------------------------------------------
    # Default configuration
    # ------------------------------------------------------------------
    app.config.setdefault("MAX_CONTENT_LENGTH", 16 * 1024 * 1024)  # 16 MB upload limit

    if config:
        app.config.update(config)

    # ------------------------------------------------------------------
    # Register blueprints
    # ------------------------------------------------------------------
    app.register_blueprint(workflows_bp)

    return app
