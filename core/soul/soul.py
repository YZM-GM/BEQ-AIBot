"""
人格模块

"""

import json
from pathlib import Path

BASE_PATH = Path(__file__).resolve().parent


class Soul:
    def __init__(self, basepath, name):
        self.soul_path = basepath / "core" / "agent" / name / "soul" / "soul.json"
        self.soul = self._load_soul()

    def _load_soul(self):
        if self.soul_path.exists():
            with open(self.soul_path, "r", encoding="utf-8") as f:
                return json.load(f)
        self.create_soul("default")
        return self.soul

    def create_soul(self, soulname="default"):
        soulpath = BASE_PATH / "souls" / (soulname + ".json")
        with open(soulpath, "r", encoding="utf-8") as f:
            self.soul = json.load(f)
        with open(self.soul_path, "w", encoding="utf-8") as f:
            json.dump(self.soul, f, ensure_ascii=False, indent=2)

    def set_soul_content(self, content):
        self.soul = content
        with open(self.soul_path, "w", encoding="utf-8") as f:
            json.dump(self.soul, f, ensure_ascii=False, indent=2)

    def GetSoul(self):
        return self.soul
