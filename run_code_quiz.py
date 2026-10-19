"""Launch the Python fill-in-the-blank quiz."""
import os
from pathlib import Path
import sys

from quiz_backend.main import main

if __name__ == '__main__':
    os.chdir(Path(__file__).resolve().parent)
    raise SystemExit(main(['code-quiz', *sys.argv[1:]]))
