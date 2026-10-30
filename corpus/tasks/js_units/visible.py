import os
import subprocess

subprocess.run([os.environ.get('CORPUS_NODE', 'node'), '-e', "const a=require('node:assert/strict'),ms=require('./');a.equal(ms('1 year'),31557600000)"], check=True)
print('visible: PASS')
