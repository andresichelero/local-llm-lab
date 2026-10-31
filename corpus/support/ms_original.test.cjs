// Run the upstream Mocha/expect.js tests unchanged with Node's built-in runner.
// The upstream file uses only equality and throw/no-throw assertions.
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function expect(value) {
  return { to: {
    be: expected => assert.strictEqual(value, expected),
    throwError: () => assert.throws(value),
    not: { throwError: () => assert.doesNotThrow(value) },
  } };
}

const original = path.resolve(process.cwd(), 'tests.js');
const context = {
  describe,
  it,
  require: name => {
    if (name === 'expect.js') return expect;
    if (name === './') return require(path.resolve(process.cwd(), 'index.js'));
    throw new Error(`Unsupported upstream import: ${name}`);
  },
};
vm.runInNewContext(fs.readFileSync(original, 'utf8'), context, { filename: original });
