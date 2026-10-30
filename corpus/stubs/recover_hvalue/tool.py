import json

print(json.dumps({'function': '_hval', 'args': ['  value  '], 'expected': '  value  ', 'tool': 'header_value_failure', 'first_attempt': 'whitespace was lost', 'retry': 'preserve value and reject controls'}, sort_keys=True))
