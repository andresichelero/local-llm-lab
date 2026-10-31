import json

print(json.dumps({'tool': 'date_check', 'first_attempt': 'FAIL: +0100 differs from equivalent GMT', 'retry': 'subtract parsed UTC offset', 'function': 'parse_date', 'args': ['Sun, 06 Nov 1994 09:49:37 +0100'], 'expected': 784111777}, sort_keys=True))
