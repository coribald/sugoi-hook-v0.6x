"""Durable game-hook profile state and stable executable identity."""

import hashlib
from pathlib import Path

from json_persistence import JsonPersistenceError, load_json_object, save_json_object_atomic


def game_identity(executable_path, executable_size):
    """Return the legacy profile key derived from the path and file size."""
    path = str(executable_path)
    return hashlib.md5(f"{path}_{executable_size}".encode()).hexdigest()


class GameProfileStore:
    def __init__(self, path=None, *, validator, issue_reporter=lambda path, error: None):
        self.path = path
        self.validator = validator
        self.issue_reporter = issue_reporter
        self.profiles = {}

    def load(self):
        self.profiles = {}
        if not self.path:
            return self.profiles
        try:
            profiles, recovered = load_json_object(self.path, self.validator)
        except JsonPersistenceError as error:
            self.issue_reporter(self.path, error)
            return self.profiles
        if profiles is not None:
            self.profiles = profiles
            if recovered:
                self.issue_reporter(self.path, "the primary file was invalid; recovered the last valid saved profiles")
        return self.profiles

    def save(self):
        if not self.path:
            return False
        try:
            save_json_object_atomic(self.path, self.profiles, self.validator)
            return True
        except JsonPersistenceError as error:
            self.issue_reporter(self.path, error)
            return False

    def commit(self, profiles):
        previous = self.profiles
        self.profiles = profiles
        if self.save():
            return True
        self.profiles = previous
        return False

    @staticmethod
    def identity_for_path(executable_path):
        path = Path(executable_path)
        return game_identity(str(path), path.stat().st_size), str(path), path.stat().st_size
