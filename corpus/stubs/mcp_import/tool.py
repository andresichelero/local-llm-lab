import json

print(json.dumps({'function': 'load', 'args': ['builtins:str("ABC")'], 'expected': 'ABC', 'tool': 'import_contract', 'rule': 'preserve case in names and expression literals'}, sort_keys=True))
