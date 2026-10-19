"""Reset selected quiz JSON files after confirmation, saving backups first."""
import os
from pathlib import Path
import sys

from quiz_backend.main import main

if __name__ == '__main__':
    os.chdir(Path(__file__).resolve().parent)
    raise SystemExit(main(['reset-json', *sys.argv[1:]]))
