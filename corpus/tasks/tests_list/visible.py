import subprocess
import sys
from pathlib import Path

assert Path('test/test_tests_list.py').is_file()
subprocess.run([sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '-q', 'test/test_tests_list.py'], check=True)
print('visible: authored tests pass')
