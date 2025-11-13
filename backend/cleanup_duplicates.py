#!/usr/bin/env python3
"""
Database Cleanup Script - Remove Duplicate Patient Records

This script identifies and removes duplicate patient records based on email address,
keeping only the oldest record for each email.

Usage:
    python cleanup_duplicates.py

Prerequisites:
    - Run this from your backend directory
    - Backup your database first!
    - Make sure your virtual environment is activated
"""

import asyncio
import sys
from datetime import datetime

try:
    from sqlalchemy import select, func, delete
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.database.db import AsyncSessionLocal
    from app.models.patient import Patient
except ImportError as e:
    print("=" * 70)
    print("❌ ERROR: Missing required modules")
    print("=" * 70)
    print()
    print("It looks like you're not running this script from the correct location")
    print("or your virtual environment is not activated.")
    print()
    print("Please follow these steps:")
    print()
    print("1. Make sure you're in the backend directory:")
    print("   cd /path/to/backend")
    print()
    print("2. Activate your virtual environment:")
    print("   source .venv/bin/activate  # On Mac/Linux")
    print("   .venv\\Scripts\\activate     # On Windows")
    print()
    print("3. Run the script:")
    print("   python cleanup_duplicates.py")
    print()
    print(f"Error details: {e}")
    print()
    sys.exit(1)


async def find_duplicates(db: AsyncSession):
    """Find all email addresses that have multiple patient records."""
    stmt = (
        select(Patient.email, func.count(Patient.id).label('count'))
        .where(Patient.email.isnot(None))
        .group_by(Patient.email)
        .having(func.count(Patient.id) > 1)
    )
    
    result = await db.execute(stmt)
    return result.all()


async def get_patients_by_email(db: AsyncSession, email: str):
    """Get all patient records for a given email, ordered by creation date."""
    stmt = (
        select(Patient)
        .where(Patient.email == email)
        .order_by(Patient.created_at.asc())  # Oldest first
    )
    
    result = await db.execute(stmt)
    return result.scalars().all()


async def cleanup_duplicate_patients(dry_run: bool = True):
    """
    Find and remove duplicate patient records, keeping the oldest one.
    
    Args:
        dry_run: If True, only show what would be deleted without actually deleting
    """
    print("=" * 70)
    print("MedFax - Database Cleanup: Duplicate Patient Records")
    print("=" * 70)
    print()
    
    if dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
        print()
    else:
        print("⚠️  LIVE MODE - Changes will be committed!")
        print()
        response = input("Are you sure you want to proceed? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            return
        print()
    
    async with AsyncSessionLocal() as db:
        # Find duplicate emails
        duplicates = await find_duplicates(db)
        
        if not duplicates:
            print("✨ No duplicate email addresses found!")
            print("   Your database is clean.")
            return
        
        print(f"Found {len(duplicates)} email address(es) with duplicates:")
        print()
        
        total_to_delete = 0
        
        for email, count in duplicates:
            print(f"📧 Email: {email}")
            print(f"   Count: {count} records")
            
            # Get all patients with this email
            patients = await get_patients_by_email(db, email)
            
            if not patients:
                continue
            
            # Keep the first (oldest) one
            keep = patients[0]
            to_delete = patients[1:]
            
            print(f"   ✅ KEEP:   ID {keep.id:4d} | Created: {keep.created_at} | Name: {keep.first_name} {keep.last_name}")
            
            for p in to_delete:
                total_to_delete += 1
                print(f"   ❌ DELETE: ID {p.id:4d} | Created: {p.created_at} | Name: {p.first_name} {p.last_name}")
            
            print()
            
            # Delete duplicates (if not dry run)
            if not dry_run and to_delete:
                delete_ids = [p.id for p in to_delete]
                await db.execute(delete(Patient).where(Patient.id.in_(delete_ids)))
        
        print("-" * 70)
        print(f"Summary: {total_to_delete} duplicate record(s) found")
        
        if not dry_run:
            await db.commit()
            print("✅ Duplicates have been removed!")
        else:
            print("ℹ️  Run with --live to actually delete these records")
        
        print()


async def add_unique_constraint_check():
    """Check if unique constraint exists on email field."""
    print()
    print("=" * 70)
    print("Checking for unique email constraint...")
    print("=" * 70)
    print()
    
    # This is database-specific, shown for reference
    print("To prevent future duplicates, add a unique constraint:")
    print()
    print("SQL:")
    print("  ALTER TABLE patients ADD CONSTRAINT uq_patient_email UNIQUE (email);")
    print()
    print("Or in your Patient model:")
    print("  email = Column(String, unique=True, index=True)")
    print()


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Clean up duplicate patient records')
    parser.add_argument(
        '--live',
        action='store_true',
        help='Actually delete duplicates (default is dry-run)'
    )
    parser.add_argument(
        '--check-constraint',
        action='store_true',
        help='Show how to add unique constraint'
    )
    
    args = parser.parse_args()
    
    try:
        if args.check_constraint:
            asyncio.run(add_unique_constraint_check())
        else:
            asyncio.run(cleanup_duplicate_patients(dry_run=not args.live))
    except KeyboardInterrupt:
        print("\n\nAborted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
