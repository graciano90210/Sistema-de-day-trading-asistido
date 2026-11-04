"""Sistema de day trading asistido — solo investigación y paper trading."""

__version__ = "0.1.0"


def main() -> None:
    from daytrader.cli import app

    app()
