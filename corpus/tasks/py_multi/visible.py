import bottle

d = bottle.MultiDict()
d.append('n', '10')
d.append('n', '20')
assert d.get('n', index=0, type=int) == 10
print('visible: PASS')
