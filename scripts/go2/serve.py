"""Serve a generated web distribution on localhost only."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    root = args.directory.resolve()
    if not (root / 'index.html').is_file():
        parser.error('Specify a generated web directory containing index.html')

    class Handler(SimpleHTTPRequestHandler):
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.js': 'text/javascript', '.bin': 'application/octet-stream'}

        def end_headers(self):
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('X-Content-Type-Options', 'nosniff')
            super().end_headers()

    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, directory=str(root)))
    print(f'Go2 Point Cloud Viewer: http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
