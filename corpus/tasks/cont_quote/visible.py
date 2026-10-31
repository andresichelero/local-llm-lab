import bottle

assert bottle.html_quote('a\tb') == '"a&#9;b"'
print('visible: PASS')
