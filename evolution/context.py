import os
import json

class EvolutionContextMap:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    def build(self) -> dict:
        # 1. Skills
        skills_dir = os.path.join(self.root, "skill")
        skills_count = 0
        if os.path.exists(skills_dir):
            for r, d, f in os.walk(skills_dir):
                if "SKILL.md" in f:
                    skills_count += 1
        
        # 2. Plugins
        plugins_dir = os.path.join(self.root, "plugins")
        plugins_count = 0
        if os.path.exists(plugins_dir):
            for r, d, f in os.walk(plugins_dir):
                if "SKILL.md" in f:
                    plugins_count += 1

        # 3. Profiles
        profiles_dir = os.path.join(self.root, "hive", "profiles")
        profiles_count = 0
        if os.path.exists(profiles_dir):
            for r, d, f in os.walk(profiles_dir):
                for file in f:
                    if file.endswith(".yaml") or file.endswith(".yml"):
                        profiles_count += 1

        # 4. RAG
        rag_index = os.path.join(self.root, "knowledge", "_rag_index.json")
        rag_present = os.path.exists(rag_index)

        # 5. Consensus
        consensus_paths = [
            "workspace/evidence_ledger.json",
            "hive/engine.py",
            "core/intelligence/moa.py",
            "evolution/omni_kernel.py",
            "evolution/hyper_kernel.py",
            "optimization/evidence_ledger.py",
        ]
        consensus_count = sum(1 for p in consensus_paths if os.path.exists(os.path.join(self.root, p)))

        return {
            "surfaces": {
                "skills": {
                    "present": skills_count > 0,
                    "count": skills_count,
                },
                "plugins": {
                    "present": plugins_count > 0,
                    "count": plugins_count,
                },
                "profiles": {
                    "present": profiles_count > 0,
                    "count": profiles_count,
                },
                "rag": {
                    "present": rag_present,
                    "count": 1 if rag_present else 0,
                },
                "consensus": {
                    "present": consensus_count > 0,
                    "count": consensus_count,
                }
            }
        }

    def as_text(self) -> str:
        data = self.build()
        surfaces = data["surfaces"]
        lines = [
            "🧬 **NEXUS Evolution Context Surface Map**:",
            f"-   **Skills**: {'Available' if surfaces['skills']['present'] else 'None'} ({surfaces['skills']['count']} registered)",
            f"-   **Plugins**: {'Active' if surfaces['plugins']['present'] else 'Inactive'} ({surfaces['plugins']['count']} loaded)",
            f"-   **Profiles**: {'Configured' if surfaces['profiles']['present'] else 'None'} ({surfaces['profiles']['count']} profiles)",
            f"-   **RAG Index**: {'Indexed' if surfaces['rag']['present'] else 'Unindexed'}",
            f"-   **Consensus Engine**: {surfaces['consensus']['count']} active nodes",
        ]
        return "\n".join(lines)
