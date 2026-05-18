import psutil

def kill_process(name):
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] == name:
            proc.terminate()