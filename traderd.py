"""traderd launcher — run from project root only."""
import sys
from pathlib import Path

# Ensure project root is on path, NOT platform/
root = Path(__file__).parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from platform.app import main
raise SystemExit(main())
