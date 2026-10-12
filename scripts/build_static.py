"""Fingerprint browser code and precompress text assets for Caddy.
Run after editing public/app.js, public/styles.css or public/index.html.
"""

import gzip
import hashlib
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "public"
html = (root / "index.html").read_text()
for source, extension, attribute in [("styles.css", "css", "href"), ("app.js", "js", "src")]:
    content = (root / source).read_bytes()
    name = hashlib.sha256(content).hexdigest()[:16] + "." + extension
    (root / "assets" / name).write_bytes(content)
    # Replace only the main stylesheet/script references; keep image attributes intact.
    if extension == "css":
        html = re.sub(r'(<link rel="stylesheet" href=")[^"]+', r"\g<1>/assets/" + name, html)
    else:
        html = re.sub(r'(<script src=")[^"]+', r"\g<1>/assets/" + name, html)
(root / "index.html").write_text(html)
for path in root.rglob("*"):
    if path.is_file() and path.suffix in {".html", ".css", ".js", ".txt", ".svg"}:
        path.with_name(path.name + ".gz").write_bytes(
            gzip.compress(path.read_bytes(), compresslevel=9, mtime=0)
        )
print("Fingerprinted browser assets and reproducible gzip files generated.")
