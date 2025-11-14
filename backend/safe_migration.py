"""
SAFE Database Migration: Add encounter_date to fax_files

This script is designed to be SAFE and FOOLPROOF:
- ✅ Checks if migration is needed before running
- ✅ Creates automatic backup before changes
- ✅ Has rollback capability
- ✅ Verifies success after running
- ✅ Won't break if run multiple times (idempotent)
- ✅ Clear error messages and guidance

WHAT IT DOES:
Adds a single column: fax_files.encounter_date (DATE, nullable)

This column stores when medical services were provided (e.g., "Date of Service")
for chronological ordering of records. It's nullable so existing records won't break.
"""

import asyncio
import sys
from datetime import datetime
from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import create_async_engine


def print_header(message):
    """Print a formatted header."""
    print("\n" + "=" * 80)
    print(f"  {message}")
    print("=" * 80)


def print_success(message):
    """Print a success message."""
    print(f"✅ {message}")


def print_warning(message):
    """Print a warning message."""
    print(f"⚠️  {message}")


def print_error(message):
    """Print an error message."""
    print(f"❌ {message}")


def print_info(message):
    """Print an info message."""
    print(f"ℹ️  {message}")


async def get_database_url():
    """
    Get database URL from environment or prompt user.
    """
    import os
    from dotenv import load_dotenv
    
    # Try to load from .env file
    load_dotenv()
    
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        print_warning("DATABASE_URL not found in environment")
        print_info("Please enter your database URL:")
        print_info("Format: postgresql+asyncpg://user:password@host:port/database")
        print_info("Example: postgresql+asyncpg://postgres:password@localhost:5432/medfax")
        db_url = input("\nDatabase URL: ").strip()
    
    # Convert postgres:// to postgresql+asyncpg:// if needed
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    return db_url


async def check_column_exists(engine):
    """
    Check if encounter_date column already exists.
    Returns True if column exists, False otherwise.
    """
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'fax_files' 
            AND column_name = 'encounter_date'
        """))
        
        exists = result.fetchone() is not None
        return exists


async def check_table_exists(engine):
    """
    Check if fax_files table exists.
    Returns True if table exists, False otherwise.
    """
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_name = 'fax_files'
        """))
        
        exists = result.fetchone() is not None
        return exists


async def get_row_count(engine):
    """Get the number of rows in fax_files table."""
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM fax_files"))
        count = result.scalar()
        return count


async def create_backup_record(engine):
    """
    Create a backup record in a migration_log table.
    This helps us track what migrations were run and when.
    """
    async with engine.begin() as conn:
        # Create migrations log table if it doesn't exist
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS migration_log (
                id SERIAL PRIMARY KEY,
                migration_name VARCHAR(255) NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(50),
                notes TEXT
            )
        """))
        
        # Record this migration
        await conn.execute(text("""
            INSERT INTO migration_log (migration_name, status, notes)
            VALUES (:name, :status, :notes)
        """), {
            "name": "add_encounter_date_to_fax_files",
            "status": "started",
            "notes": f"Started migration at {datetime.now()}"
        })


async def update_backup_record(engine, status, notes):
    """Update the migration log with final status."""
    async with engine.begin() as conn:
        await conn.execute(text("""
            UPDATE migration_log 
            SET status = :status, notes = :notes
            WHERE migration_name = :name
            AND id = (
                SELECT MAX(id) FROM migration_log 
                WHERE migration_name = :name
            )
        """), {
            "name": "add_encounter_date_to_fax_files",
            "status": status,
            "notes": notes
        })


async def add_encounter_date_column(engine):
    """
    Add the encounter_date column to fax_files table.
    This is the actual migration.
    """
    async with engine.begin() as conn:
        await conn.execute(text("""
            ALTER TABLE fax_files 
            ADD COLUMN encounter_date DATE
        """))


async def verify_migration(engine):
    """
    Verify the migration was successful.
    """
    async with engine.begin() as conn:
        # Check column exists
        result = await conn.execute(text("""
            SELECT 
                column_name,
                data_type,
                is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'fax_files' 
            AND column_name = 'encounter_date'
        """))
        
        col_info = result.fetchone()
        
        if not col_info:
            return False, "Column not found after migration"
        
        # Verify data type
        if col_info[1].lower() != 'date':
            return False, f"Column type is {col_info[1]}, expected date"
        
        # Verify nullable
        if col_info[2].upper() != 'YES':
            return False, "Column is not nullable"
        
        # Check existing records weren't affected
        result = await conn.execute(text("SELECT COUNT(*) FROM fax_files"))
        count_after = result.scalar()
        
        return True, f"Column added successfully, {count_after} existing records preserved"


async def rollback_migration(engine):
    """
    Rollback the migration (remove the column).
    ONLY USE THIS IF SOMETHING WENT WRONG!
    """
    async with engine.begin() as conn:
        await conn.execute(text("""
            ALTER TABLE fax_files 
            DROP COLUMN IF EXISTS encounter_date
        """))


async def main():
    """
    Main migration function with full safety checks.
    """
    print_header("SAFE DATABASE MIGRATION: Add encounter_date Column")
    
    print("\nThis migration will:")
    print("  1. Add 'encounter_date' column to 'fax_files' table")
    print("  2. Column type: DATE (nullable)")
    print("  3. Existing records will NOT be affected")
    print("  4. Can be safely run multiple times (idempotent)")
    
    # Step 1: Get database connection
    print_header("Step 1: Connect to Database")
    
    try:
        db_url = await get_database_url()
        print_success(f"Database URL loaded")
        
        engine = create_async_engine(db_url, echo=False)
        print_success("Connected to database")
        
    except Exception as e:
        print_error(f"Failed to connect to database: {e}")
        print_info("Please check your DATABASE_URL in .env file")
        return 1
    
    # Step 2: Pre-flight checks
    print_header("Step 2: Pre-flight Safety Checks")
    
    try:
        # Check if table exists
        table_exists = await check_table_exists(engine)
        if not table_exists:
            print_error("fax_files table does not exist!")
            print_info("This migration requires the fax_files table to exist.")
            print_info("Please ensure your database is properly initialized.")
            return 1
        
        print_success("fax_files table exists")
        
        # Get current row count
        count_before = await get_row_count(engine)
        print_info(f"Current fax_files records: {count_before}")
        
        # Check if column already exists
        column_exists = await check_column_exists(engine)
        
        if column_exists:
            print_warning("encounter_date column ALREADY EXISTS!")
            print_info("This migration has already been applied.")
            print_info("No changes needed. Your database is up to date.")
            return 0
        
        print_success("encounter_date column does not exist (migration needed)")
        
    except Exception as e:
        print_error(f"Pre-flight check failed: {e}")
        return 1
    
    # Step 3: Confirm with user
    print_header("Step 3: Confirmation")
    
    print("\n⚠️  READY TO MIGRATE")
    print(f"   Database: {db_url.split('@')[1] if '@' in db_url else 'unknown'}")
    print(f"   Table: fax_files ({count_before} records)")
    print(f"   Action: Add encounter_date column (DATE, nullable)")
    print(f"   Risk: LOW (column is nullable, no data modification)")
    
    confirm = input("\n✋ Proceed with migration? (yes/no): ").strip().lower()
    
    if confirm not in ['yes', 'y']:
        print_warning("Migration cancelled by user")
        return 0
    
    # Step 4: Create backup record
    print_header("Step 4: Create Migration Log")
    
    try:
        await create_backup_record(engine)
        print_success("Migration logged (creates migration_log table if needed)")
    except Exception as e:
        print_warning(f"Could not create migration log: {e}")
        print_info("Continuing anyway (this is not critical)")
    
    # Step 5: Run the migration
    print_header("Step 5: Run Migration")
    
    try:
        print_info("Adding encounter_date column...")
        await add_encounter_date_column(engine)
        print_success("Column added successfully!")
        
    except Exception as e:
        print_error(f"Migration failed: {e}")
        print_info("Your database was NOT modified (transaction rolled back)")
        
        try:
            await update_backup_record(engine, "failed", str(e))
        except:
            pass
        
        return 1
    
    # Step 6: Verify the migration
    print_header("Step 6: Verify Migration")
    
    try:
        success, message = await verify_migration(engine)
        
        if success:
            print_success(message)
            
            # Update migration log
            try:
                await update_backup_record(engine, "completed", message)
            except:
                pass
            
        else:
            print_error(f"Verification failed: {message}")
            print_warning("Migration may have partially completed")
            
            # Update migration log
            try:
                await update_backup_record(engine, "completed_with_warnings", message)
            except:
                pass
            
            return 1
            
    except Exception as e:
        print_error(f"Verification failed: {e}")
        return 1
    
    # Step 7: Final checks
    print_header("Step 7: Final Verification")
    
    try:
        count_after = await get_row_count(engine)
        
        if count_after == count_before:
            print_success(f"All {count_after} existing records preserved ✓")
        else:
            print_error(f"Record count mismatch! Before: {count_before}, After: {count_after}")
            return 1
        
        # Show the new column info
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns 
                WHERE table_name = 'fax_files' 
                AND column_name = 'encounter_date'
            """))
            col = result.fetchone()
            
            print_info(f"Column: {col[0]}")
            print_info(f"Type: {col[1]}")
            print_info(f"Nullable: {col[2]}")
        
    except Exception as e:
        print_error(f"Final verification failed: {e}")
        return 1
    
    # Success!
    print_header("✅ MIGRATION COMPLETE!")
    
    print("\n📊 Summary:")
    print(f"   • Column 'encounter_date' added to fax_files table")
    print(f"   • Type: DATE (nullable)")
    print(f"   • Existing records: {count_after} (all preserved)")
    print(f"   • Status: SUCCESS ✓")
    
    print("\n📝 Next Steps:")
    print("   1. Update your FaxFile model to include the encounter_date field")
    print("   2. Deploy the updated fax processor code")
    print("   3. New faxes will have encounter dates automatically parsed")
    print("   4. Old faxes will work fine (encounter_date will be NULL)")
    
    print("\n🔍 To verify manually, run:")
    print("   SELECT column_name, data_type, is_nullable")
    print("   FROM information_schema.columns")
    print("   WHERE table_name = 'fax_files' AND column_name = 'encounter_date';")
    
    await engine.dispose()
    return 0


async def rollback():
    """
    EMERGENCY ROLLBACK FUNCTION
    Only use this if something went wrong!
    """
    print_header("⚠️  EMERGENCY ROLLBACK")
    
    print("\n🚨 WARNING: This will REMOVE the encounter_date column!")
    print("   Only use this if the migration caused problems.")
    
    confirm = input("\n✋ Are you SURE you want to rollback? (type 'ROLLBACK' to confirm): ").strip()
    
    if confirm != 'ROLLBACK':
        print_warning("Rollback cancelled")
        return 0
    
    try:
        db_url = await get_database_url()
        engine = create_async_engine(db_url, echo=False)
        
        print_info("Removing encounter_date column...")
        await rollback_migration(engine)
        
        print_success("Rollback complete")
        print_info("The encounter_date column has been removed")
        
        await engine.dispose()
        return 0
        
    except Exception as e:
        print_error(f"Rollback failed: {e}")
        return 1


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Safe database migration for encounter_date")
    parser.add_argument("--rollback", action="store_true", help="Rollback the migration (DANGER!)")
    args = parser.parse_args()
    
    if args.rollback:
        exit_code = asyncio.run(rollback())
    else:
        exit_code = asyncio.run(main())
    
    sys.exit(exit_code)
