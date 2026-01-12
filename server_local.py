
import oracledb
from mcp.server.fastmcp import FastMCP

LIB_DIR = r"C:\oracle\instantclient_11_2" 
DB_USER = "HARI"     
DB_PASS = "HARI123" 
DB_HOST = "localhost" 
DB_PORT = "1521"
DB_SID  = "databaseai"       

try:
    oracledb.init_oracle_client(lib_dir=LIB_DIR)
except Exception as e:
    print(f"FATAL: {e}")
    exit(1)

# Nama server dibedakan biar tidak bingung di log
mcp = FastMCP("Oracle10g-Local")

def get_connection():
    dsn = oracledb.makedsn(DB_HOST, DB_PORT, sid=DB_SID)
    return oracledb.connect(user=DB_USER, password=DB_PASS, dsn=dsn)

@mcp.tool()
def list_tables() -> str:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Batasi cuma 20 tabel biar Ollama gak pusing
        cursor.execute("SELECT table_name FROM user_tables WHERE ROWNUM <= 20")
        tables = [row[0] for row in cursor.fetchall()]
        return f"Tabel (Top 20): {', '.join(tables)}"
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()

@mcp.tool()
def run_sql(query: str) -> str:
    # Safety guard
    if any(x in query.lower() for x in ["drop", "delete", "truncate", "update"]):
        return "DENIED"

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query)
        if cursor.description:
            cols = [c[0] for c in cursor.description]
        else:
            return "No Data"

        # OPTIMASI: Cuma ambil 50 baris
        rows = cursor.fetchmany(50)
        
        output = [f"Columns: {cols}"]
        for row in rows:
            output.append(str(row))
            
        return "\n".join(output)
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()

if __name__ == "__main__":
    mcp.run()