import sqlite3
from tools.qlvb_downloader.index_db import init_db, get_default_db_path, upsert_document
from tools.qlvb_downloader.config import QLVBConfig

def check():
    db_path = get_default_db_path("Data")
    print(f"Checking DB at {db_path}")
    
    # Run init which triggers migration
    init_db(db_path)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("PRAGMA table_info(documents);")
    columns = [row["name"] for row in cursor.fetchall()]
    print(f"Columns: {columns}")
    
    # Check if migration added the new columns
    for col in ["source_category", "source_url", "knowledge_candidate", "planner_candidate"]:
        if col in columns:
            print(f"✅ Column {col} exists.")
        else:
            print(f"❌ Column {col} missing!")
            
    # Run init again to test idempotency
    init_db_if_not_exists(db_path)
    print("✅ Ran init_db again without errors (Idempotency checked)")
    
    # Check old data (if any)
    docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    print(f"Total documents in DB: {docs}")

if __name__ == "__main__":
    check()
