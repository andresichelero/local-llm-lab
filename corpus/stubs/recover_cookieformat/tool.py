import json

print(json.dumps({'function': 'cookie_is_encoded', 'args': [{'bytes': [33, 97, 63, 98]}], 'expected': True, 'tool': 'cookie_format_failure', 'first_attempt': 'signed cookie rejected', 'retry': 'require prefix and separator, without removing whitespace'}, sort_keys=True))
