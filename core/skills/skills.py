"""
skills类模块
"""

from .skillsmanager import get_skillsinfo


class Skills:
    def __init__(self, basepath, allow_skills=None):
        self.skills = get_skillsinfo()
        self.create_skill(allow_skills)

    def create_skill(self, allow_skills=None):
        enabled_skills = {
            name: meta
            for name, meta in self.skills.items()
            if isinstance(meta, dict) and meta.get("enabled", True)
        }
        if allow_skills is None:
            self.skills = enabled_skills
            return

        allow_set = set(allow_skills)
        self.skills = {
            name: meta
            for name, meta in enabled_skills.items()
            if name in allow_set
        }

    def GetSkills(self):
        return str([
            f"{name}:{meta.get('summary', '')}"
            for name, meta in self.skills.items()
        ])
