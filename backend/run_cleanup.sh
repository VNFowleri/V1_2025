#!/bin/bash

# Wrapper script to run cleanup_duplicates.py with proper environment
# This ensures the virtual environment is activated and the script runs correctly

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BACKEND_DIR="$SCRIPT_DIR"

echo "================================"
echo "MedFax - Cleanup Script Runner"
echo "================================"
echo ""

# Check if we're in the backend directory
if [ ! -f "$BACKEND_DIR/app/main.py" ]; then
    echo "❌ Error: This script must be run from the backend directory"
    echo ""
    echo "Current directory: $PWD"
    echo ""
    echo "Please run:"
    echo "  cd /path/to/backend"
    echo "  bash cleanup_duplicates.sh"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "$BACKEND_DIR/.venv" ]; then
    echo "❌ Error: Virtual environment not found at .venv/"
    echo ""
    echo "Please create it first:"
    echo "  python -m venv .venv"
    echo "  source .venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Activate virtual environment
echo "🔄 Activating virtual environment..."
source "$BACKEND_DIR/.venv/bin/activate"

# Check if sqlalchemy is installed
if ! python -c "import sqlalchemy" 2>/dev/null; then
    echo "❌ Error: SQLAlchemy not installed in virtual environment"
    echo ""
    echo "Please install dependencies:"
    echo "  source .venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

echo "✅ Virtual environment activated"
echo ""

# Run the cleanup script with any arguments passed to this script
python "$BACKEND_DIR/cleanup_duplicates.py" "$@"
