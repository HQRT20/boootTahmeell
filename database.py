import json
import os

DB_FILE = 'users.json'

if not os.path.exists(DB_FILE):
    with open(DB_FILE, 'w') as f:
        json.dump({}, f)


def _load():
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _save(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


DEFAULTS = {
    "banned_users": [],
    "force_subscribe_channels": [],
    "user_ids": []
}

_data = _load()
for key, default_value in DEFAULTS.items():
    if key not in _data:
        _data[key] = default_value
_save(_data)


class DB:

    def get(self, key):
        return _load().get(key)

    def set(self, key, value):
        data = _load()
        data[key] = value
        _save(data)

    def delete(self, key):
        data = _load()
        data.pop(key, None)
        _save(data)

    def exists(self, key):
        return key in _load()


db = DB()
