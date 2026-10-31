import bottle

assert bottle.path_shift('/app', '/one/two/', 1) == ('/app/one', '/two/')
print('visible: PASS')
