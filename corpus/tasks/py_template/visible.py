import bottle

t = bottle.SimpleTemplate('Hello {{name}}')
assert t.render({'name': 'first'}, name='second') == 'Hello second'
print('visible: PASS')
