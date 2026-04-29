import os

import uvicorn

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    uvicorn.run(
        "app.asgi:create_asgi_app",
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5050")),
        factory=True,
        reload=False,
        ws="wsproto",
        log_level="debug" if debug else "info",
    )
