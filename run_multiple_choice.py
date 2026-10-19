"""Launch the multiple-choice quiz using this project's settings and data."""
import os
from pathlib import Path
import sys

from quiz_backend.main import main

if __name__ == '__main__':
    os.chdir(Path(__file__).resolve().parent)
    raise SystemExit(main(['term-quiz', *sys.argv[1:]]))
