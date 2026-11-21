import errno
import os
import socket
from pathlib import Path

from dotenv import load_dotenv
from uvicorn import Config, Server


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    configured_port = os.getenv('WIFI_PORT')
    try:
        port = int(configured_port or '8000')
        if not 0 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise SystemExit('WIFI_PORT phải là số nguyên từ 0 đến 65535.') from None

    host = '127.0.0.1'
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((host, port))
        except OSError as error:
            if error.errno != errno.EADDRINUSE:
                raise
            if configured_port:
                raise SystemExit(f'Cổng {port} đang được sử dụng. Hãy chọn WIFI_PORT khác.') from None
            listener.bind((host, 0))
            print(f'Cổng {port} đang được sử dụng. Dashboard sẽ chạy trên cổng trống khác.', flush=True)

        port = listener.getsockname()[1]
        config = Config('backend.app.main:app', host=host, port=port)
        server = Server(config)
        print(f'Mở http://{host}:{port} — Ctrl+C để dừng', flush=True)
        server.run(sockets=[listener])
    if not server.started:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
