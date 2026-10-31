import bottle

assert bottle.path_shift('/app', '/x/y', 1) == ('/app/x', '/y') and bottle.path_shift('/app/x', '/y', -1) == ('/app', '/x/y')
print('visible: PASS')
