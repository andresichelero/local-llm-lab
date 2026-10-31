import bottle

assert bottle.html_escape('<') == '&lt;'
print('visible: PASS')
