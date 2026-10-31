import bottle

assert isinstance(bottle._hkey('content-type'), str)
print('visible: PASS')
