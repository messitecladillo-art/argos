import os

from app import create_app


app = create_app()


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5050")),
        debug=debug,
        use_reloader=debug,
        use_debugger=debug,
    )
