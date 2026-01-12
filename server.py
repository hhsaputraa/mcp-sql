import os
import logging
import re
from contextlib import contextmanager
import oracledb
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

LIB_DIR = os.getenv("ORACLE_LIB_DIR", r"C:\oracle\instantclient_11_2")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "1521")
DB_SID  = os.getenv("DB_SID", "databaseai")

if not all([DB_USER, DB_PASS, DB_HOST]):
    logger.error("Missing database credentials in .env")
    
try:
    oracledb.init_oracle_client(lib_dir=LIB_DIR)
    logger.info("Oracle Client (Thick Mode) loaded successfully.")
except Exception as e:
    logger.fatal(f"Failed to load Oracle Client: {e}")
    
pool = None
try:
    if all([DB_USER, DB_PASS, DB_HOST]):
        pool = oracledb.SessionPool(
            user=DB_USER,
            password=DB_PASS,
            dsn=oracledb.makedsn(DB_HOST, DB_PORT, sid=DB_SID),
            min=1,
            max=5,
            increment=1
        )
        logger.info("Oracle Connection Pool created.")
except Exception as e:
    logger.fatal(f"Failed to create connection pool: {e}")

mcp = FastMCP("Oracle10g-Legacy-Bridge")

@contextmanager
def get_db_connection():
    """Context manager for acquiring a connection from the pool."""
    if not pool:
        raise Exception("Database connection pool is not initialized.")
    
    connection = None
    try:
        connection = pool.acquire()
        yield connection
    except Exception as e:
        logger.error(f"Error getting connection: {e}")
        raise
    finally:
        if connection:
            pool.release(connection)

@mcp.tool()
def list_tables() -> str:
    """Retrieves a list of tables accessible to the user."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT table_name FROM user_tables ORDER BY table_name")
                tables = [row[0] for row in cursor.fetchall()]
                return f"Found {len(tables)} tables: {', '.join(tables)}"
    except Exception as e:
        logger.error(f"Error listing tables: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def run_sql(query: str) -> str:
    """
    Executes a SELECT SQL query.
    IMPORTANT: Use legacy Oracle syntax (e.g., ROWNUM instead of OFFSET/FETCH).
    """
    forbidden_pattern = re.compile(r'\b(drop|delete|truncate|update|insert|alter|grant|revoke|create|replace)\b', re.IGNORECASE)
    
    if forbidden_pattern.search(query):
        logger.warning(f"Blocked destructive query: {query}")
        return "DENIED: Destructive operations (DROP, DELETE, UPDATE, etc.) are strictly forbidden."

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                
                if cursor.description is None:
                    return "Query executed successfully (No output)."

                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                
                output = [f"Columns: {', '.join(columns)}"]
                for row in rows:
                    output.append(str(row))
                    
                limit_msg = ""
                if len(rows) >= 50:
                    limit_msg = "\n... (Output truncated to 50 rows)"
                
                return "\n".join(output[:50]) + limit_msg
                
    except oracledb.DatabaseError as e:
        error_obj, = e.args
        logger.error(f"Oracle SQL Error: {error_obj.message}")
        return f"Oracle Error Code {error_obj.code}: {error_obj.message}"
    except Exception as e:
        logger.error(f"General Error running SQL: {e}")
        return f"System Error: {str(e)}"

@mcp.tool()
def describe_table(table_name: str) -> str:
    """
    Retrieves the schema (columns, types) of a specific table.
    Useful when a query fails due to 'invalid identifier' or to understand table structure.
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT column_name, data_type, data_length 
                    FROM user_tab_columns 
                    WHERE table_name = :1
                    ORDER BY column_id
                """
                cursor.execute(query, [table_name.upper()])
                rows = cursor.fetchall()
                
                if not rows:
                    return f"Table '{table_name}' not found."

                output = [f"Schema for {table_name}:"]
                for row in rows:
                    output.append(f"- {row[0]} ({row[1]}, {row[2]})")
                
                return "\n".join(output)
    except Exception as e:
        logger.error(f"Error describing table {table_name}: {e}")
        return f"Error: {str(e)}"

if __name__ == "__main__":
    try:
        mcp.run()
    except KeyboardInterrupt:
        pass
    finally:
        if pool:
            pool.close()
            logger.info("Connection pool closed.")