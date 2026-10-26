import os
import pyodbc
from dotenv import load_dotenv

# Load .env
load_dotenv()

server = os.getenv("SQL_SERVER")
port = os.getenv("SQL_PORT")
database = os.getenv("SQL_DATABASE")
user = os.getenv("SQL_USER")
password = os.getenv("SQL_PASSWORD")

connection_string = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={server},{port};"
    f"DATABASE={database};"
    f"UID={user};"
    f"PWD={password};"
    "Encrypt=no;"
    "TrustServerCertificate=yes;"
    "Connection Timeout=5;"
)

print("------------------------------------------------")
print("Testing SQL Server connection...")
print(f"Server   : {server}")
print(f"Port     : {port}")
print(f"Database : {database}")
print(f"User     : {user}")
print("------------------------------------------------")

try:
    conn = pyodbc.connect(connection_string)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            @@SERVERNAME,
            DB_NAME(),
            @@VERSION
    """)

    row = cursor.fetchone()

    print()
    print("✅ CONNECTION SUCCESSFUL")
    print("----------------------------------------")
    print("Server   :", row[0])
    print("Database :", row[1])
    print("----------------------------------------")
    print(row[2])

    conn.close()

except Exception as ex:
    print()
    print("❌ CONNECTION FAILED")
    print("----------------------------------------")
    print(ex)