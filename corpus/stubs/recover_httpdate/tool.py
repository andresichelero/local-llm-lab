import json

print(json.dumps({'function': 'http_date', 'args': [0], 'expected': 'Thu, 01 Jan 1970 00:00:00 GMT', 'tool': 'http_date_failure', 'first_attempt': 'date has numeric timezone instead of GMT', 'retry': 'preserve strings and produce GMT'}, sort_keys=True))
