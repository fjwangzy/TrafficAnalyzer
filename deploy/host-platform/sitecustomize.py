"""Resolve libpq from the private host runtime without changing host ldconfig."""
import ctypes.util
import os
from pathlib import Path

_find_library = ctypes.util.find_library


def _private_find_library(name):
    if name == 'c' and os.environ.get('HOST_RUNTIME_LOADER'):
        return str(Path(os.environ['HOST_RUNTIME_LOADER']).parent / 'libc.so.6')
    directory = os.environ.get('HIGHGO_LIBRARY_DIR')
    if name == 'pq' and directory:
        path = Path(directory) / 'libpq.so.5'
        if path.is_file():
            return str(path)
    return _find_library(name)


ctypes.util.find_library = _private_find_library
