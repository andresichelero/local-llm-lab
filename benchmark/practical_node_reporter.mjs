/** Trusted parent reporter for JavaScript acceptance checks (post-audit Task 1).
 *
 * The reporter never trusts the candidate.  It parses the trusted check
 * source itself to enumerate expected node:test case ids, reruns the TAP
 * stream of a spawned `node --test` worker, and accepts only complete
 * column-zero anchor pairs from within that stream; candidate console
 * output inside the worker arrives comment-escaped and can never forge a
 * verdict anchor or a result line.  Missing, repeated, skipped, extra, or
 * indented results, mispaired anchors, and abrupt termination produce an
 * invalid report status awaiting review instead of an approval.
 */

import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

export const SCHEMA = 'practical-grade-report-v1';
export const SEED_FILE_NAME = '.practical-grade-seed.json';
export const STOPS = ['pass', 'fail', 'error', 'skipped'];
const TEST_CALL_RE = /\btest\(\s*(['"])([^\n'"]{1,400}?)\1/g;
const NONCE_RE = /^[0-9a-f]{32}$/;
const DEFAULT_DEADLINE_MS = 18000;

export const reportExportPaths = (nonce) => [
  `.practical-grade-${nonce}.json`,
  `.practical-grade-${nonce}-2.json`,
  `.practical-grade-${nonce}-3.json`,
  `.practical-grade-${nonce}-late.json`,
];

export function nodeCheckCaseIds(source) {
  const ids = [];
  for (const match of source.matchAll(TEST_CALL_RE)) {
    ids.push(match[2].replaceAll("\\'", "'").replaceAll('\\"', '"'));
  }
  return ids;
}

function parseArgs(argv) {
  const args = { deadline: DEFAULT_DEADLINE_MS };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (flag === '--checks' && index + 1 < argv.length) {
      args.checks = argv[++index];
    } else if (flag === '--seed-file' && index + 1 < argv.length) {
      args.seedFile = argv[++index];
    } else if (flag === '--nonce' && index + 1 < argv.length) {
      args.nonce = argv[++index];
    } else if (flag === '--workspace' && index + 1 < argv.length) {
      args.workspace = argv[++index];
    } else if (flag === '--deadline' && index + 1 < argv.length) {
      const deadline = Number(argv[++index]);
      args.deadline = Number.isFinite(deadline) && deadline > 0
        ? deadline : DEFAULT_DEADLINE_MS;
    } else if (flag === '--') {
      continue;
    } else {
      return null;
    }
  }
  if (args.checks === undefined) return null;
  if (args.seedFile === undefined && args.nonce === undefined) return null;
  return args;
}

export function readNonce(workspace, args) {
  if (args.nonce !== undefined) {
    return NONCE_RE.test(args.nonce) ? args.nonce : null;
  }
  const seed = path.join(workspace, args.seedFile ?? SEED_FILE_NAME);
  let payload;
  try {
    payload = JSON.parse(fs.readFileSync(seed, 'utf8'));
  } catch {
    return null;
  }
  try {
    fs.unlinkSync(seed);
  } catch {
    return null;
  }
  const nonce = payload?.nonce;
  return typeof nonce === 'string' && NONCE_RE.test(nonce) ? nonce : null;
}

/** Column-zero anchor pair evaluation over a TAP text. */
export function evaluateTap(text, expectedList) {
  const expectedSet = new Set(expectedList);
  const anchored = [];
  const resolved = new Map();
  let mimicry = '';
  let pending = null;
  const flag = (reason) => { mimicry ||= reason; };
  for (const raw of text.split('\n')) {
    const line = raw.endsWith('\r') ? raw.slice(0, -1) : raw;
    if (line.startsWith('# Subtest: ')) {
      const id = line.slice('# Subtest: '.length);
      if (resolved.has(id)) {
        flag('repeat-anchors');
      } else if (anchored.includes(id)) {
        flag('repeat-anchors');
      } else {
        anchored.push(id);
      }
      pending = id;
      continue;
    }
    const result = line.match(/^(ok|not ok) (\d+) - (.*)$/);
    if (result !== null) {
      let rest = result[3];
      let stop = result[1] === 'ok' ? 'pass' : 'fail';
      const mark = rest.indexOf(' # ');
      if (mark !== -1) {
        const trailer = rest.slice(mark + 3);
        rest = rest.slice(0, mark);
        if (trailer.startsWith('SKIP') || trailer.startsWith('TODO')) {
          stop = 'skipped';
        } else {
          flag('unknown-trailer');
        }
      }
      if (resolved.has(rest)) {
        flag('repeat-results');
      } else {
        resolved.set(rest, stop);
      }
      if (pending !== rest) flag('mispaired');
      pending = null;
      continue;
    }
    if (line === '' || line.startsWith('# ') || line.startsWith(' ')) continue;
    if (line.startsWith('TAP version ') || line.startsWith('1..')) continue;
    flag('unknown-lines');
  }
  const outside = [...resolved.keys()].filter((id) => !expectedSet.has(id));
  const orphanAnchors = [...new Set(anchored)]
    .filter((id) => !resolved.has(id) && !expectedSet.has(id));
  const missing = expectedList.filter((id) => !resolved.has(id));
  const orphanExpected = anchored
    .filter((id) => expectedSet.has(id) && !resolved.has(id));
  return { resolved, mimicry, outside, orphanAnchors, missing, orphanExpected };
}

export function buildReport(nonce, expectedList, evaluation, spawn) {
  const header = { schema: SCHEMA, nonce, expected_case_ids: expectedList };
  const { resolved, mimicry, outside, orphanAnchors, missing } = evaluation;
  if (mimicry || outside.length || orphanAnchors.length) {
    const names = [...outside, ...orphanAnchors].slice(0, 6);
    return {
      ...header,
      status: 'invalid',
      reason: 'grade stream carried untrusted structure'
        + (names.length ? `: ${names.join(', ')}` : ''),
      checks: [],
      tests_run: resolved.size,
    };
  }
  if (missing.length || spawn.timedOut === true || spawn.status < 0) {
    const reason = [];
    if (missing.length) {
      reason.push(`checks terminated before: ${missing.slice(0, 6).join(', ')}`);
    }
    if (spawn.timedOut === true) {
      reason.push('grade worker deadline exceeded');
    } else if (spawn.status < 0) {
      reason.push(`grade worker died with signal ${spawn.signal}`);
    } else {
      reason.push(`grade worker exited ${spawn.status}`);
    }
    return {
      ...header,
      status: 'invalid',
      reason: reason.join('; ') || 'grade worker did not finish',
      checks: [],
      tests_run: resolved.size,
    };
  }
  const checks = expectedList.map((id) => ({ id, stop: resolved.get(id) }));
  return { ...header, status: 'complete', checks, tests_run: expectedList.length };
}

export function writeReport(workspace, nonce, report) {
  const payload = Buffer.from(JSON.stringify(report), 'utf8');
  for (const name of reportExportPaths(nonce)) {
    const target = path.join(workspace, name);
    let fd;
    try {
      fd = fs.openSync(target, 'wx', 0o644);
    } catch {
      continue; // occupied slot or filesystem failure: next slot
    }
    try {
      fs.writeFileSync(fd, payload);
      fs.fsyncSync(fd);
    } catch {
      // fall through to the next slot
    } finally {
      fs.closeSync(fd);
    }
    return 0;
  }
  return 5;
}

export function runReporter(args, spawnFn) {
  const workspace = args.workspace ?? process.cwd();
  const nonce = readNonce(workspace, args);
  if (nonce === null) return 3;
  let source;
  try {
    source = fs.readFileSync(args.checks, 'utf8');
  } catch {
    return 3;
  }
  const expectedList = [...new Set(nodeCheckCaseIds(source))];
  if (expectedList.length === 0) return 3;
  const slot = reportExportPaths(nonce)
    .find((name) => !fs.existsSync(path.join(workspace, name)));
  if (slot === undefined) return 4;
  const spawn = spawnFn(process.execPath,
    ['--test', '--test-reporter=tap', args.checks],
    {
      ...spawnOptions(workspace, args.deadline),
    });
  const evaluation = evaluateTap(spawn.stdout?.toString('utf8') ?? '',
    expectedList);
  const report = buildReport(nonce, expectedList, evaluation, spawn);
  return writeReport(workspace, nonce, report);
}

function spawnOptions(workspace, deadlineMs) {
  return {
    cwd: workspace,
    timeout: deadlineMs,
    killSignal: 'SIGKILL',
    maxBuffer: 4 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { PYTHONDONTWRITEBYTECODE: '1', PATH: '/usr/bin:/bin' },
  };
}

const current = process.argv[1];
if (current && import.meta.url === pathToFileURL(current).href) {
  const args = parseArgs(process.argv.slice(2));
  if (args === null) {
    process.exit(2);
  }
  process.exit(runReporter(args, spawnSync));
}
