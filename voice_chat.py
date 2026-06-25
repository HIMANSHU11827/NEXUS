import sys
import os

# Add project root to path
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

from voice.voice_chat import main

if __name__ == "__main__":
    main()
