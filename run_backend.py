"""Start the Obsidian HTTP bridge using this project's settings."""
import os
from pathlib import Path

from quiz_backend.api import main

if __name__ == '__main__':
    os.chdir(Path(__file__).resolve().parent)
    main()
