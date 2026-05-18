import sqlite3

class DatabaseConnectorTool:
    """NEXUS DATABASE DRIVER 1.0"""
    def __init__(self, db_path: str = "./workspace/nexus_main.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
    def execute_query(self, query: str, params: tuple = ()) -> list:
        try:
            self.cursor.execute(query, params)
            self.conn.commit()
            return self.cursor.fetchall()
        except Exception as e: return [f"Error: {str(e)}"]
