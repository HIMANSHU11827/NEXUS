import sqlite3

def query_db(db_path, sql):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(sql)
    res = cur.fetchall()
    conn.close()
    return res