import psutil
import platform

def get_telemetry():
    return {
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent,
        "os": platform.system()
    }