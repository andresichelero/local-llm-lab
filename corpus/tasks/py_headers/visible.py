import bottle

h = bottle.HeaderDict()
h.append('Content-Type', 'text/plain')
assert h.get('content-type') == 'text/plain'
print('visible: PASS')
