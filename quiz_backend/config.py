"""Settings persist in DATA_PATH/settings.json; environment variables win."""
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re

from .notes.storage import read_json, write_json


@dataclass
class Settings:
    vault_path: str = "./vault"
    data_path: str = "./data"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3"
    ollama_timeout: float = 120
    sandbox_timeout: float = 5
    sandbox_memory: str = "128m"
    sandbox_cpus: float = 0.5
    sandbox_image: str = "python:3.13-alpine"
    python_libraries: str = ""
    default_quiz_length: int = 10
    default_code_difficulty: str = "medium"

    def validate(self):
        if not self.vault_path.strip() or not self.data_path.strip():
            raise ValueError("Vault and data paths cannot be empty.")
        if not self.ollama_url.startswith(("http://", "https://")) or not self.ollama_model.strip():
            raise ValueError("Set an HTTP Ollama URL and a model name.")
        if not all(0 < value <= 3600 for value in (self.ollama_timeout, self.sandbox_timeout)):
            raise ValueError("Timeouts must be between 0 and 3600 seconds.")
        if not re.fullmatch(r"[1-9]\d*[kmg]", self.sandbox_memory.lower()):
            raise ValueError("Memory must look like 128m or 1g.")
        if not 0 < self.sandbox_cpus <= 16 or self.default_quiz_length < 0:
            raise ValueError("CPU limit must be in (0, 16]; quiz length cannot be negative.")
        if self.default_code_difficulty not in ("easy", "medium", "hard"):
            raise ValueError("Difficulty must be easy, medium, or hard.")
        return self


def load_settings() -> Settings:
    data_path = os.getenv("DATA_PATH", "./data")
    saved = read_json(Path(data_path) / "settings.json", dict)
    defaults = asdict(Settings())
    values = {}
    for key, default in defaults.items():
        value = os.getenv(key.upper(), saved.get(key, default))
        try:
            values[key] = type(default)(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid setting: {key}") from exc
    values["data_path"] = data_path
    return Settings(**values).validate()


def save_settings(settings: Settings):
    settings.validate()
    write_json(Path(settings.data_path) / "settings.json", asdict(settings))
