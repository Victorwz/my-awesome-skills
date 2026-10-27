"""Tiny static server with HTTP Range support (browsers need Range to seek in an mp4) for sharing review cuts.

  nohup python serve.py <dir> [port] > serve.log 2>&1 &      # default port 8081, binds 0.0.0.0
  pkill -f "serve.py"                                        # stop

Put an index.html with <video controls src="cut.mp4"> in <dir>, or symlink the cuts there, and share
http://<host-ip>:<port>/.  Refreshing the page after a re-render picks up the new file.
"""
import os, re, sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

class H(SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.translate_path(self.path)
        rng = self.headers.get("Range")
        if not rng or os.path.isdir(path) or not os.path.exists(path):
            return super().send_head()
        size = os.path.getsize(path)
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        start = int(m[1]) if m and m[1] else 0
        end = min(int(m[2]) if m and m[2] else size - 1, size - 1)
        if start >= size:
            self.send_error(416); return None
        f = open(path, "rb"); f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._remaining = end - start + 1
        return f

    def copyfile(self, src, dst):
        n = getattr(self, "_remaining", None)
        if n is None:
            return super().copyfile(src, dst)
        while n > 0:
            buf = src.read(min(1 << 20, n))
            if not buf: break
            try: dst.write(buf)
            except (BrokenPipeError, ConnectionResetError): break
            n -= len(buf)

if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8081
    os.chdir(root)
    print(f"serving {os.path.abspath(root)} on 0.0.0.0:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
