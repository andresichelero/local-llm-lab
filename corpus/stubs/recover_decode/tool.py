import json

print(json.dumps({'tool': 'decode_test_runner', 'first_attempt': 'UnicodeDecodeError despite replacement policy', 'retry': 'honor the specified decode error policy', 'function': 'touni', 'args': [{'bytes': [255]}, 'utf8', 'replace'], 'expected': '�'}, sort_keys=True))
