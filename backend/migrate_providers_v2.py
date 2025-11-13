#!/usr/bin/env python3
"""
Database Migration - Add Medical Records Fields to Provider Model

This script adds new fields to the providers table to support:
- Medical records department specific contact info
- Fax number verification metadata
- Hospital website URLs

Usage:
    python migrate_providers_v2.py

Prerequisites:
    - Run from your backend directory
    - Backup your database first!
    - Virtual environment activated
"""

import asyncio
import sys
from sqlalchemy import text

try:
    from app.database.db import AsyncSessionLocal, engine
except ImportError as e:
    print("=" * 70)
    print("❌ ERROR: Missing required modules")
    print("=" * 70)
    print()
    print("Please make sure you're in the backend directory and")
    print("your virtual environment is activated.")
    print()
    print(f"Error details: {e}")
    print()
    sys.exit(1)


async def check_column_exists(db, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    try:
        # SQLite
        result = await db.execute(text(f"PRAGMA table_info({table})"))
        columns = [row[1] for row in result.fetchall()]
        return column in columns
    except:
        try:
            # PostgreSQL
            result = await db.execute(text(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_name = '{table}' AND column_name = '{column}'"
            ))
            return result.fetchone() is not None
        except:
            return False


async def migrate():
    """Run the migration."""
    print("=" * 70)
    print("Provider Model Migration - v2.0")
    print("=" * 70)
    print()
    
    async with AsyncSessionLocal() as db:
        # Define new columns to add
        new_columns = {
            'medical_records_fax': 'VARCHAR',
            'medical_records_phone': 'VARCHAR',
            'medical_records_email': 'VARCHAR',
            'fax_verified': 'BOOLEAN DEFAULT FALSE',
            'fax_verification_source': 'VARCHAR',
            'fax_verification_url': 'TEXT',
            'fax_confidence_score': 'FLOAT',
            'website': 'VARCHAR',
        }
        
        print("Checking existing columns...")
        
        for column, col_type in new_columns.items():
            exists = await check_column_exists(db, 'providers', column)
            
            if exists:
                print(f"  ✓ Column '{column}' already exists, skipping")
            else:
                print(f"  + Adding column '{column}' ({col_type})...")
                
                try:
                    await db.execute(text(
                        f"ALTER TABLE providers ADD COLUMN {column} {col_type}"
                    ))
                    await db.commit()
                    print(f"    ✅ Successfully added '{column}'")
                except Exception as e:
                    print(f"    ❌ Error adding '{column}': {e}")
                    # Continue with other columns
        
        print()
        print("=" * 70)
        print("✅ Migration complete!")
        print("=" * 70)
        print()
        print("Next steps:")
        print("1. Restart your backend server")
        print("2. New providers will automatically use the new fields")
        print("3. Existing providers can be updated with medical records fax numbers")
        print()


if __name__ == "__main__":
    try:
        asyncio.run(migrate())
    except KeyboardInterrupt:
        print("\n\nAborted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
