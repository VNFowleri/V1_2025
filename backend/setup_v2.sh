#!/bin/bash
# setup_v2.sh - Automated setup script for Medical Records v2.0 upgrade

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  Veritas One - Medical Records System v2.0 Upgrade Setup     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check if we're in the backend directory
if [ ! -f "$SCRIPT_DIR/app/main.py" ]; then
    echo "❌ Error: This script must be run from the backend directory"
    echo ""
    echo "Current directory: $PWD"
    echo ""
    echo "Please run:"
    echo "  cd /path/to/backend"
    echo "  bash setup_v2.sh"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "❌ Error: Virtual environment not found at .venv/"
    echo ""
    echo "Please create it first:"
    echo "  python3 -m venv .venv"
    echo "  source .venv/bin/activate"
    exit 1
fi

echo "🔄 Step 1/5: Activating virtual environment..."
source "$SCRIPT_DIR/.venv/bin/activate"
echo "✅ Virtual environment activated"
echo ""

echo "🔄 Step 2/5: Installing new dependencies..."
echo "   - beautifulsoup4 (web scraping)"
echo "   - lxml (HTML parsing)"
echo "   - rapidfuzz (fuzzy matching)"
echo "   - html5lib (HTML parsing)"
echo ""
pip install -q beautifulsoup4==4.12.3 lxml==5.1.0 rapidfuzz==3.6.1 html5lib==1.1
echo "✅ Dependencies installed"
echo ""

echo "🔄 Step 3/5: Backing up database..."
if [ -f "$SCRIPT_DIR/dev.db" ]; then
    cp "$SCRIPT_DIR/dev.db" "$SCRIPT_DIR/dev.db.backup.$(date +%Y%m%d_%H%M%S)"
    echo "✅ Database backed up"
else
    echo "⚠️  No database found (first run?)"
fi
echo ""

echo "🔄 Step 4/5: Running database migration..."
python "$SCRIPT_DIR/migrate_providers_v2.py"
echo ""

echo "🔄 Step 5/5: Verifying installation..."

# Test imports
python -c "
import sys
try:
    from app.services.medical_records_finder import MedicalRecordsFinder
    from app.services.hospital_directory import search_hospitals
    from rapidfuzz import fuzz
    from bs4 import BeautifulSoup
    print('✅ All modules imported successfully')
except ImportError as e:
    print(f'❌ Import error: {e}')
    sys.exit(1)
"

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                   ✅ INSTALLATION COMPLETE                     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "🎉 Your system has been upgraded to v2.0!"
echo ""
echo "📋 What's New:"
echo "   • Intelligent medical records fax discovery"
echo "   • Fuzzy matching for hospital name search"
echo "   • Enhanced location search (city/state/ZIP)"
echo "   • Fax verification indicators in UI"
echo "   • Multi-source hospital database aggregation"
echo ""
echo "🚀 Next Steps:"
echo ""
echo "   1. Start/restart your backend server:"
echo "      uvicorn app.main:app --reload --port 8000"
echo ""
echo "   2. Test the new features:"
echo "      • Try searching for 'Mayo Clinic'"
echo "      • Try misspelling: 'Massechusetts General'"
echo "      • Try location: City='Boston', State='MA'"
echo ""
echo "   3. (Optional) Configure Google Custom Search API:"
echo "      • Get API key from Google Cloud Console"
echo "      • Add to .env file:"
echo "        GOOGLE_SEARCH_API_KEY=your_key"
echo "        GOOGLE_SEARCH_CX=your_cx_id"
echo ""
echo "   4. Read the full implementation guide:"
echo "      cat IMPLEMENTATION_GUIDE.md"
echo ""
echo "💡 Tips:"
echo "   • Without Google API, users can still manually add fax numbers"
echo "   • Fax numbers are cached in DB for faster subsequent searches"
echo "   • Check logs for fax discovery success rates"
echo ""
echo "📞 Need Help?"
echo "   • Check IMPLEMENTATION_GUIDE.md for troubleshooting"
echo "   • Review logs for any errors"
echo "   • Test with known hospitals first"
echo ""
echo "────────────────────────────────────────────────────────────────"
echo "Ready to go! Happy faxing! 📠✨"
echo ""
