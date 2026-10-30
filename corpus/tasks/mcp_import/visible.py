import bottle

assert bottle.load('builtins:str("XYZ")') == 'XYZ'
print('visible: PASS')
