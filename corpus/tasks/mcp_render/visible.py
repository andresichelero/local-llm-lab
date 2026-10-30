import bottle

assert bottle.template("{{ '<i>' }}") == '&lt;i&gt;'
print('visible: PASS')
