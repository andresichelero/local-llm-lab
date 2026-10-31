import os
import subprocess

subprocess.run([os.environ.get('CORPUS_NODE', 'node'), '-e', "const a=require('node:assert/strict'),ms=require('./');a.equal(ms('1.5 hours'),5400000)"], check=True)
print('visible: PASS')
