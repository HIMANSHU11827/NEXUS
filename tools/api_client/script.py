import requests

class RestApiClientTool:
    """NEXUS API DRIVER 1.0"""
    def call(self, method: str, url: str, data: dict = None):
        try:
            response = requests.request(method, url, json=data)
            return response.json()
        except Exception as e: return {"error": f"API Call Failed: {str(e)}"}
