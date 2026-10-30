import os
import subprocess


def test_private_contract():
    result = subprocess.run([os.environ['CORPUS_NODE'], '-e', "try { const a=require('node:assert/strict'),ms=require('./');a.equal(ms('1.5 hours'),5400000);a.equal(ms('-.5H'),-1800000);a.equal(ms('2   MINS'),120000);a.equal(ms('.25'),0.25); console.log('PASS'); } catch (e) { if (e && e.code === 'ERR_ASSERTION') { console.log('ASSERT'); process.exitCode = 1; } else { console.error(e); process.exitCode = 2; } }"], capture_output=True, check=False)
    if (result.returncode, result.stdout.strip()) not in {(0, b'PASS'), (1, b'ASSERT')}:
        raise RuntimeError('JavaScript oracle infrastructure failure')
    assert result.returncode == 0
