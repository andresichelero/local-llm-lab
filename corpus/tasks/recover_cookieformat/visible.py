import bottle

assert bottle.cookie_is_encoded(b'!x?y')
print('visible: PASS')
