import bottle

r = bottle.Router()
r.add('/n/<n:int>', 'GET', 'target')
assert r.match({'PATH_INFO': '/n/42', 'REQUEST_METHOD': 'GET'}) == ('target', {'n': 42})
print('visible: PASS')
