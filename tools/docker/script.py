import subprocess

class DockerOpsTool:
    """NEXUS DOCKER DRIVER 1.0"""
    def run_container(self, image: str, cmd: str) -> str:
        try:
            result = subprocess.run(["docker", "run", "--rm", image, "sh", "-c", cmd], capture_output=True, text=True, timeout=60)
            return result.stdout if result.returncode == 0 else result.stderr
        except Exception as e: return f"Error: {str(e)}"
