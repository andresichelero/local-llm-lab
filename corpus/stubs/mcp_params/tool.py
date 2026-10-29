import json

print(json.dumps({'tool': 'header_diagnostic', 'function': '_parse_http_header', 'args': ['text/plain; CHARSET=UTF-8'], 'expected': [['text/plain', {'charset': 'UTF-8'}]], 'observed': 'parameter CHARSET not found', 'rule': 'parameter names are case-insensitive'}, sort_keys=True))
