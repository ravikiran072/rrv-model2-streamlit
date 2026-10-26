"""Launch the Model 2 website: python app.py (requires NumPy)."""
import argparse
import os
import threading
import webbrowser
from http.server import ThreadingHTTPServer


def main():
    parser = argparse.ArgumentParser(description="Launch the Raccoon Rabies Model 2 website")
    parser.add_argument("--host", default=os.environ.get("RRV_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    from server import Handler, initialize
    initialize()
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        parser.exit(1, f"Cannot start server: {exc}. Try --port 8766.\n")
    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"
    print(f"Model 2 website: {url}\nPress Ctrl+C to stop.", flush=True)
    if not args.no_browser:
        threading.Timer(.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
