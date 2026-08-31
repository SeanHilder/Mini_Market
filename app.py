"""Local entry point. See README.md for setup and configuration."""

from mini_market import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
