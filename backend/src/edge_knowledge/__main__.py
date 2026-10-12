import json
import socket

import uvicorn

from edge_knowledge.bootstrap import build_app
from edge_knowledge.infrastructure.config import RuntimeConfig


def main():
    config = RuntimeConfig()
    application = build_app(config)
    # Bind before announcing the port: no free-port lookup / spawn race.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", config.port))
        listener.listen(128)
        print(json.dumps({"event": "backend_ready", "port": listener.getsockname()[1]}), flush=True)
        server = uvicorn.Server(uvicorn.Config(application, log_level="warning", access_log=False))
        server.run(sockets=[listener])


if __name__ == "__main__":
    main()
