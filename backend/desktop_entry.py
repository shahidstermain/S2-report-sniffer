import os
import uvicorn


def main():
    host = os.environ.get("S2RS_HOST", "127.0.0.1")
    port = int(os.environ.get("S2RS_PORT", "8000"))
    log_level = os.environ.get("S2RS_LOG_LEVEL", "info")
    uvicorn.run("server:app", host=host, port=port, log_level=log_level, reload=False)


if __name__ == "__main__":
    main()

