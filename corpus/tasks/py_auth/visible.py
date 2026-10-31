import bottle

import base64
header = 'Basic ' + base64.b64encode(b'user:a:b').decode()
assert bottle.parse_auth(header) == ('user', 'a:b')
print('visible: PASS')
