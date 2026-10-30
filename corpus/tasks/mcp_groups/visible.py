import bottle

assert bottle._re_flatten('(x)') == '(?:x)'
print('visible: PASS')
