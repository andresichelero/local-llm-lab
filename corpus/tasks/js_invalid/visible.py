import os
import subprocess

subprocess.run([os.environ.get('CORPUS_NODE', 'node'), '-e', "const a=require('node:assert/strict'),ms=require('./');a.throws(()=>ms(Infinity));a.equal(ms(' '),undefined)"], check=True)
print('visible: PASS')
