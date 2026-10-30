import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
runpy.run_path(str(Path(__file__).with_name('visible.py')), run_name='__main__')
