from __future__ import annotations

import uvicorn

from server.app import app


if __name__ == "__main__":
    config = app.state.config
    uvicorn.run(app, host=config.host, port=config.port, log_level="info", access_log=True)
