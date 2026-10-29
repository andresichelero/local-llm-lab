import json

print(json.dumps({'tool': 'header_contract', 'function': '_hkey', 'args': ['x_request_id'], 'expected': 'X-Request-Id', 'rule': 'underscores map to hyphens'}, sort_keys=True))
