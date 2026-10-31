import json

print(json.dumps({'function': '_re_flatten', 'args': ['(abc)'], 'expected': '(?:abc)', 'tool': 'regex_contract', 'rule': 'capturing groups become noncapturing; escaped parentheses remain literal'}, sort_keys=True))
