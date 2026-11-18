import logging

import uvicorn

from app.config import get_settings


if __name__ == "__main__":
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s level=%(levelname)s logger=%(name)s %(message)s")
    uvicorn.run("app.main:create_app", factory=True, host=settings.app_host, port=settings.app_port,
                log_level=settings.log_level.lower())
