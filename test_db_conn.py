import psycopg
from dotenv import load_dotenv
import os

load_dotenv()

# Get connection string from .env
DATABASE_URL = os.getenv('DATABASE_URL')

try:
    # Connect to database (psycopg3 syntax)
    with psycopg.connect(DATABASE_URL) as conn:
        
        # Create cursor
        with conn.cursor() as cur:
            
            # Test query
            cur.execute("SELECT version();")
            db_version = cur.fetchone()
            print(f"✅ Connected successfully!")
            print(f"PostgreSQL version: {db_version[0]}")
            
            # Check your databases
            cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
            databases = cur.fetchall()
            print(f"\n📊 Available databases:")
            for db in databases:
                print(f"  - {db[0]}")
            
            # Check tables in current database
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """)
            tables = cur.fetchall()
            print(f"\n📋 Tables in fms_db ({len(tables)} tables):")
            for table in tables:
                print(f"  - {table[0]}")
            
            # Count records in tables (fixed query for PostgreSQL 18)
            if tables:
                cur.execute("""
                    SELECT 
                        schemaname,
                        relname as tablename,
                        n_live_tup as row_count
                    FROM pg_stat_user_tables
                    ORDER BY n_live_tup DESC
                    LIMIT 10;
                """)
                stats = cur.fetchall()
                print(f"\n📈 Table statistics (top 10 by row count):")
                for stat in stats:
                    print(f"  - {stat[1]}: {stat[2]:,} rows")
            else:
                print(f"\n⚠️  No tables found yet (database is empty)")
    
    print(f"\n✅ Connection test completed successfully!")
    
except psycopg.Error as e:
    print(f"❌ Database connection failed!")
    print(f"Error: {e}")
except Exception as e:
    print(f"❌ Error: {e}")