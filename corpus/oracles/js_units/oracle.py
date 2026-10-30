import os
import subprocess


def test_private_contract():
    result = subprocess.run([os.environ['CORPUS_NODE'], '-e', "try { const a=require('node:assert/strict'),ms=require('./');a.equal(ms('1 year'),31557600000);a.equal(ms('1.5 YRS'),47336400000);a.equal(ms('2 weeks'),1209600000);a.equal(ms('.5W'),302400000);a.equal(ms(3600000),'1h');a.equal(ms(3600000,{long:true}),'1 hour');a.equal(ms(3599999),'60m');a.equal(ms(5400000),'2h');a.equal(ms(5400000,{long:true}),'2 hours'); console.log('PASS'); } catch (e) { if (e && e.code === 'ERR_ASSERTION') { console.log('ASSERT'); process.exitCode = 1; } else { console.error(e); process.exitCode = 2; } }"], capture_output=True, check=False)
    if (result.returncode, result.stdout.strip()) not in {(0, b'PASS'), (1, b'ASSERT')}:
        raise RuntimeError('JavaScript oracle infrastructure failure')
    assert result.returncode == 0
