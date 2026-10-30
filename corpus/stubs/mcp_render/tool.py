import json

print(json.dumps({'function': 'template', 'args': ["{{! '<b>' }}"], 'expected': '<b>', 'tool': 'render_contract', 'rule': 'ordinary expressions escape HTML; ! expressions remain raw'}, sort_keys=True))
