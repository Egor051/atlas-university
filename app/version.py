"""One release identity, derived only from public application source."""
from pathlib import Path
from functools import lru_cache
import hashlib

VERSION = '3.2.1'

@lru_cache(maxsize=1)
def build_id():
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for folder in ('app', 'static'):
        for source in sorted((root / folder).glob('*')):
            if source.suffix in {'.py', '.js', '.css', '.html', '.svg'}:
                digest.update(source.relative_to(root).as_posix().encode())
                digest.update(source.read_bytes())
    return digest.hexdigest()[:16]
