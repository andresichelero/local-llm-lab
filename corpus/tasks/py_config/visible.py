import bottle

c = bottle.ConfigDict()
c.load_dict({'a': {'b': {'c': 1}}})
assert c.get('a.b.c') == 1
print('visible: PASS')
