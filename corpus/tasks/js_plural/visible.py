import os
import subprocess

subprocess.run([os.environ.get('CORPUS_NODE', 'node'), '-e', "const a=require('node:assert/strict'),ms=require('./');a.equal(ms(1500,{long:true}),'2 seconds')"], check=True)
print('visible: PASS')
