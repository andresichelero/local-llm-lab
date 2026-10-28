/** Data-only candidate worker and trusted synchronous import proxies. */
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import Module from 'node:module';
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads';

const LIMIT = 1024 * 1024;
const HEADER = 16;
const arg = (name) => process.argv[process.argv.indexOf(name) + 1];

function readExact(fd, count) {
  const out = Buffer.alloc(count);
  let offset = 0;
  while (offset < count) {
    const size = fs.readSync(fd, out, offset, count - offset, null);
    if (!size) throw new Error('RPC channel ended');
    offset += size;
  }
  return out;
}
function readFrame(fd) {
  const size = readExact(fd, 4).readUInt32BE();
  if (!size || size > LIMIT) throw new Error('RPC frame bound');
  return JSON.parse(readExact(fd, size).toString('utf8'));
}
function writeFrame(fd, value) {
  const data = Buffer.from(JSON.stringify(value));
  if (data.length > LIMIT) throw new Error('RPC response bound');
  const head = Buffer.alloc(4); head.writeUInt32BE(data.length);
  for (const buffer of [head, data]) {
    let offset = 0;
    while (offset < buffer.length) offset += fs.writeSync(fd, buffer, offset);
  }
}

class Graph {
  constructor(prefix) { this.prefix = prefix; this.objects = new Map(); this.ids = new WeakMap(); this.next = 0; }
  encode(value, nodes) {
    if (value === undefined) return { $undefined: true };
    if (typeof value === 'number' && !Number.isFinite(value)) return { $float: String(value) };
    if (typeof value === 'number' && Object.is(value, -0)) return { $float: '-0' };
    if (typeof value === 'bigint') return { $bigint: String(value) };
    if (value === null || typeof value !== 'object') {
      if (['function', 'symbol'].includes(typeof value)) throw new Error('Unsupported RPC value');
      return value;
    }
    let id = this.ids.get(value);
    if (!id) { id = `${this.prefix}${this.next++}`; this.ids.set(value, id); this.objects.set(id, value); }
    if (!(id in nodes)) {
      nodes[id] = null;
      nodes[id] = { kind: Array.isArray(value) ? 'array' : 'object',
        nullPrototype: Object.getPrototypeOf(value) === null, frozen: Object.isFrozen(value),
        entries: Object.keys(value).map(k => [k, this.encode(value[k], nodes)]),
        length: Array.isArray(value) ? value.length : undefined };
    }
    return { $ref: id };
  }
  allNodes(nodes) { for (const value of this.objects.values()) this.encode(value, nodes); }
  decode(value) {
    if (!value || typeof value !== 'object') return value;
    if ('$undefined' in value) return undefined;
    if ('$float' in value) return value.$float === '-0' ? -0 : Number(value.$float);
    if ('$bigint' in value) return BigInt(value.$bigint);
    if ('$ref' in value) {
      if (!this.objects.has(value.$ref)) throw new Error('RPC dangling reference');
      return this.objects.get(value.$ref);
    }
    throw new Error('RPC value shape');
  }
  apply(nodes) {
    if (!nodes || typeof nodes !== 'object' || Array.isArray(nodes)) throw new Error('RPC graph shape');
    for (const [id, node] of Object.entries(nodes)) {
      if (!node || !['array', 'object'].includes(node.kind) || !Array.isArray(node.entries)) throw new Error('RPC node shape');
      if (!this.objects.has(id)) {
        const object = node.kind === 'array' ? [] : (node.nullPrototype ? Object.create(null) : {});
        this.objects.set(id, object); this.ids.set(object, id);
      }
    }
    for (const [id, node] of Object.entries(nodes)) {
      const object = this.objects.get(id);
      if (Object.isFrozen(object)) continue;
      for (const key of Object.keys(object)) delete object[key];
      if (Array.isArray(object)) object.length = node.length;
      for (const [key, item] of node.entries) Object.defineProperty(object, key, {
        value: this.decode(item), writable: true, enumerable: true, configurable: true });
    }
    for (const [id, node] of Object.entries(nodes)) if (node.frozen) Object.freeze(this.objects.get(id));
  }
}

async function ioThread() {
  parentPort.on('message', ({ request, shared }) => {
    const flags = new Int32Array(shared, 0, 4);
    const bytes = new Uint8Array(shared, HEADER);
    const channel = net.createConnection(workerData.socket);
    let data = Buffer.alloc(0); let done = false;
    const finish = (result) => {
      if (done) return; done = true;
      const encoded = Buffer.from(JSON.stringify(result));
      if (encoded.length > bytes.length) { Atomics.store(flags, 0, -1); }
      else { bytes.set(encoded); Atomics.store(flags, 1, encoded.length); Atomics.store(flags, 0, 1); }
      Atomics.notify(flags, 0); channel.destroy();
    };
    channel.setTimeout(20000, () => finish({ type: 'rpc_fault', reason: 'trusted RPC deadline' }));
    channel.on('connect', () => {
      const body = Buffer.from(JSON.stringify(request)); const head = Buffer.alloc(4);
      head.writeUInt32BE(body.length); channel.write(Buffer.concat([head, body]));
    });
    channel.on('data', chunk => {
      data = Buffer.concat([data, chunk]);
      if (data.length > LIMIT + 4) return finish({ type:'rpc_fault', reason:'RPC response bound' });
      if (data.length >= 4) {
        const size = data.readUInt32BE();
        if (size > LIMIT) return finish({ type:'rpc_fault', reason:'RPC response bound' });
        if (data.length >= size + 4) {
          try { finish(JSON.parse(data.subarray(4, size + 4).toString('utf8'))); }
          catch { finish({ type:'rpc_fault', reason:'RPC JSON malformed' }); }
        }
      }
    });
    channel.on('error', error => finish({ type:'rpc_fault', reason:error.code ?? 'RPC unavailable' }));
    channel.on('end', () => { if (!done) finish({ type:'rpc_fault', reason:'RPC response truncated' }); });
  });
}

function trustedChecker() {
  const socket = arg('--rpc-socket'); const checks = arg('--checks');
  const workspace = path.resolve(arg('--workspace'));
  const graph = new Graph('h'); let serial = 0;
  const io = new Worker(new URL(import.meta.url), { workerData:{ socket } }); io.unref();
  const proxies = new Map();
  const invoke = (operation, module, name, args = []) => {
    const nodes = {}; const encoded = args.map(value => graph.encode(value, nodes)); graph.allNodes(nodes);
    const request = { type:'request', id:serial++, op:operation, module, name, args:encoded, nodes };
    const shared = new SharedArrayBuffer(LIMIT + HEADER); const flags = new Int32Array(shared, 0, 4);
    io.postMessage({ request, shared });
    if (Atomics.wait(flags, 0, 0, 22000) === 'timed-out' || Atomics.load(flags, 0) !== 1) throw new Error('trusted RPC unavailable');
    const response = JSON.parse(Buffer.from(new Uint8Array(shared, HEADER, Atomics.load(flags, 1))).toString('utf8'));
    if (response.type !== 'response' || response.id !== request.id) throw new Error(response.reason ?? 'candidate RPC protocol violation');
    graph.apply(response.nodes ?? {});
    if (!response.ok) {
      const ErrorType = ({ TypeError, RangeError, SyntaxError, ReferenceError })[response.error?.type] ?? Error;
      throw new ErrorType(response.error?.message ?? 'candidate failed');
    }
    if (response.function) return (...values) => invoke('call', module, name, values);
    return graph.decode(response.value);
  };
  const originalLoad = Module._load;
  Module._load = function (request, parent, isMain) {
    const resolved = Module._resolveFilename(request, parent, isMain);
    if (typeof resolved === 'string' && path.isAbsolute(resolved)
        && (resolved === workspace || resolved.startsWith(workspace + path.sep))) {
      if (!proxies.has(resolved)) proxies.set(resolved, new Proxy({}, {
        get: (_object, name) => typeof name === 'string' ? invoke('get', resolved, name) : undefined,
      }));
      return proxies.get(resolved);
    }
    return originalLoad.call(this, request, parent, isMain);
  };
  const harness = new Module(checks); harness.filename = checks;
  harness.paths = Module._nodeModulePaths(path.dirname(checks));
  harness._compile(fs.readFileSync(checks, 'utf8'), checks);
}

function candidateWorker() {
  const fd = Number(arg('--rpc-fd')); const workspace = path.resolve(arg('--workspace'));
  const require = Module.createRequire(import.meta.url); const graph = new Graph('w');
  while (true) {
    let request;
    try { request = readFrame(fd); } catch { return; }
    if (request.type === 'stop') return;
    if (request.type !== 'request') return;
    let stage = 'candidate_import';
    try {
      const modulePath = path.resolve(request.module);
      if (!modulePath.startsWith(workspace + path.sep)) throw new Error('candidate module outside workspace');
      graph.apply(request.nodes);
      const exported = require(modulePath);
      stage = 'candidate_call';
      const value = request.op === 'get' ? exported[request.name]
        : exported[request.name](...(request.args ?? []).map(item => graph.decode(item)));
      const nodes = {}; const encoded = typeof value === 'function' ? undefined : graph.encode(value, nodes);
      graph.allNodes(nodes);
      writeFrame(fd, { type:'response', id:request.id, ok:true, function:typeof value === 'function', value:encoded, nodes });
    } catch (error) {
      const nodes = {}; graph.allNodes(nodes);
      writeFrame(fd, { type:'response', id:request.id, ok:false, nodes, stage,
        error:{ type:error?.name ?? 'Error', message:String(error?.message ?? error) } });
    }
  }
}

if (!isMainThread) await ioThread();
else if (process.argv.includes('--candidate-worker')) candidateWorker();
else if (process.argv.includes('--trusted-checker')) trustedChecker();
else throw new Error('explicit grading role required');
