#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { spawn, execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const required = ['PI_PACKAGE', 'PI_AGENT_DIR', 'PI_WORKSPACE', 'PI_MODELS_JSON', 'PI_OUTPUT_JSONL'];
for (const key of required) if (!process.env[key]) throw new Error(`Missing ${key}`);
const packageEntry = path.join(process.env.PI_PACKAGE, 'dist/index.js');
const { createAgentSession, ModelRuntime, SessionManager, SettingsManager } = await import(pathToFileURL(packageEntry));
const workspace = path.resolve(process.env.PI_WORKSPACE);
const agentDir = path.resolve(process.env.PI_AGENT_DIR);
const outFile = path.resolve(process.env.PI_OUTPUT_JSONL);
const gitSha = execFileSync('git', ['-C', process.env.PI_REPO_ROOT, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
const sourceStatus = execFileSync('git', ['-C', process.env.PI_REPO_ROOT, 'status', '--porcelain', '--untracked-files=all', '--', '.', ':(exclude)results/**'], { encoding: 'utf8' }).trim();
fs.mkdirSync(workspace, { recursive: true });
fs.mkdirSync(agentDir, { recursive: true });
fs.mkdirSync(path.dirname(outFile), { recursive: true });

const secret = 'GLACIER-47-MAPLE';
const words = ['amber', 'birch', 'cobalt', 'delta', 'ember', 'frost', 'granite', 'harbor', 'indigo', 'juniper'];
const fingerprints = Array.from({ length: 32 }, (_, n) => createHash('sha256').update(`pi-context-stress-2026|archive-${String(n + 1).padStart(2, '0')}`).digest('hex').slice(0, 12).toUpperCase());
for (let i = 1; i <= 32; i++) {
  const lines = [];
  for (let j = 0; j < 28; j++) {
    const a = words[(i + j) % words.length];
    const b = words[(i * 3 + j * 2) % words.length];
    lines.push(`Record ${i}-${j}: ${a} ${b} ${a}-${j} is a synthetic benchmark record used only to create deterministic repository context. Its value has no operational meaning. Verify indexes before using it.`);
  }
  lines.push(`ARCHIVE FINGERPRINT: ${fingerprints[i - 1]}. Record this exact value in the manifest.`);
  if (i === 7) lines.push(`ARCHIVE RECOVERY KEY: ${secret}. Preserve this exact value for the final verification.`);
  fs.writeFileSync(path.join(workspace, `archive-${String(i).padStart(2, '0')}.md`), `# Archive ${i}\n\n${lines.join('\n')}${i === 7 ? '\n' : ''}`);
}
fs.writeFileSync(path.join(workspace, 'README.md'), '# Pi context stress fixture\n\nSynthetic files for a local context-compaction benchmark.\n');
fs.writeFileSync(path.join(workspace, 'test_result.py'), [
  'from pathlib import Path',
  'import unittest',
  'class ResultTests(unittest.TestCase):',
  '    def test_summary_exists(self):',
  '        p = Path(__file__).with_name("summary.md")',
  '        self.assertTrue(p.exists())',
  '        self.assertIn("archive_count: 32", p.read_text())',
  '    def test_manifest_has_every_fingerprint(self):',
  '        import hashlib',
  '        expected = [f"archive-{i:02d}=" + hashlib.sha256(f"pi-context-stress-2026|archive-{i:02d}".encode()).hexdigest()[:12].upper() for i in range(1, 33)]',
  '        p = Path(__file__).with_name("archive_manifest.txt")',
  '        self.assertEqual(p.read_text().splitlines(), expected)',
  'if __name__ == "__main__": unittest.main()',
  '',
].join('\n'));

fs.writeFileSync(path.join(agentDir, 'settings.json'), JSON.stringify({
  defaultTools: ['read', 'bash', 'edit', 'write', 'grep', 'find', 'ls'],
  defaultProjectTrust: 'always',
  quietStartup: true,
  compaction: { enabled: true, reserveTokens: 2048, keepRecentTokens: 4096 },
  retry: { enabled: false },
}, null, 2));
fs.copyFileSync(process.env.PI_MODELS_JSON, path.join(agentDir, 'models.json'));
fs.writeFileSync(path.join(agentDir, 'auth.json'), '{}\n');

const modelRuntime = await ModelRuntime.create({
  modelsPath: path.join(agentDir, 'models.json'),
  authPath: path.join(agentDir, 'auth.json'),
  allowModelNetwork: false,
  refreshOnCreate: false,
});
const model = modelRuntime.getModel('local-llama', 'Qwen3.5-9B-Q4_K_M');
if (!model) throw new Error('Configured local model was not resolved');
const sessionManager = SessionManager.create(workspace, path.join(agentDir, 'sessions'));
const settingsManager = SettingsManager.create(workspace, agentDir);
const { session } = await createAgentSession({
  cwd: workspace,
  agentDir,
  modelRuntime,
  model,
  thinkingLevel: 'off',
  tools: ['read', 'bash', 'edit', 'write', 'grep', 'find', 'ls'],
  sessionManager,
  settingsManager,
});

const events = [];
let compactions = 0;
let toolCalls = 0;
const unsubscribe = session.subscribe(event => {
  if (event.type === 'compaction_start' || event.type === 'compaction_end') {
    if (event.type === 'compaction_start') compactions++;
    events.push({ type: event.type, reason: event.reason, at: new Date().toISOString() });
  } else if (event.type === 'tool_execution_start') {
    toolCalls++;
    events.push({ type: event.type, tool: event.toolName ?? event.tool?.name ?? 'unknown' });
  } else if (event.type === 'tool_execution_end') {
    events.push({ type: event.type, tool: event.toolName ?? event.tool?.name ?? 'unknown', isError: Boolean(event.isError) });
  } else if (event.type === 'agent_end') {
    events.push({ type: event.type, willRetry: event.willRetry });
  }
});
const usage = () => session.getContextUsage() ?? null;
const samples = [{ label: 'start', usage: usage(), entries: sessionManager.getEntryCount() }];
const t0 = Date.now();
let phase1Error;
try {
  await session.prompt('We are in a synthetic benchmark repo. Inspect every file archive-01.md through archive-32.md using the read tool, in batches. For each file, copy its exact ARCHIVE FINGERPRINT to archive_manifest.txt as one line `archive-NN=FINGERPRINT`, in numeric order. Find the exact ARCHIVE RECOVERY KEY in archive-07.md and preserve it in summary.md as `recovery_key: <exact value>`. Include exactly `archive_count: 32` and a short description. Run `python3 test_result.py`; it verifies every fingerprint, and you must fix any mismatch by inspecting the relevant archive. The next task will ask you to recover the key after context compaction.');
} catch (error) { phase1Error = String(error); }
await session.waitForIdle();
samples.push({ label: 'after_phase_1', usage: usage(), entries: sessionManager.getEntryCount() });

let phase2Error;
try {
  await session.prompt('This is a new continuation task after the archive inspection and context compaction. Using the exact key preserved in the task state or summary.md, write only that key into recovery.txt. Do not reopen any archive file. Run `python3 test_result.py` and report the recovered key and whether compaction occurred.');
} catch (error) { phase2Error = String(error); }
await session.waitForIdle();
samples.push({ label: 'after_phase_2', usage: usage(), entries: sessionManager.getEntryCount() });
unsubscribe();

const entries = sessionManager.getEntries();
const compactionEntries = entries.filter(entry => entry.type === 'compaction').map(entry => ({ tokensBefore: entry.tokensBefore, summaryChars: entry.summary?.length ?? 0 }));
const stats = session.getSessionStats();
const summaryText = fs.existsSync(path.join(workspace, 'summary.md')) ? fs.readFileSync(path.join(workspace, 'summary.md'), 'utf8') : '';
const recoveryText = fs.existsSync(path.join(workspace, 'recovery.txt')) ? fs.readFileSync(path.join(workspace, 'recovery.txt'), 'utf8') : '';
const manifestText = fs.existsSync(path.join(workspace, 'archive_manifest.txt')) ? fs.readFileSync(path.join(workspace, 'archive_manifest.txt'), 'utf8').trim().split(/\r?\n/) : [];
const test = await new Promise(resolve => {
  const child = spawn('python3', ['test_result.py'], { cwd: workspace, stdio: 'pipe' });
  let out = '';
  child.stdout.on('data', chunk => out += chunk);
  child.stderr.on('data', chunk => out += chunk);
  child.on('close', code => resolve({ exitCode: code, output: out.slice(-4000) }));
});

const record = {
  schema_version: 1,
  timestamp: new Date().toISOString(),
  experiment: 'pi_local_context_compaction_stress',
  harness: 'Pi SDK',
  model: 'Qwen3.5-9B-Q4_K_M',
  git_sha: gitSha,
  source_tree_dirty: Boolean(sourceStatus),
  context_window: 16384,
  compaction_settings: { enabled: true, reserve_tokens: 2048, keep_recent_tokens: 4096 },
  storage_profile: 'C: SSD via WSL2 ext4; no HDD benchmark I/O',
  elapsed_ms: Date.now() - t0,
  phase1_error: phase1Error ?? null,
  phase2_error: phase2Error ?? null,
  context_samples: samples,
  compaction_events: compactionEntries,
  compaction_event_count: compactions,
  tool_call_start_count: toolCalls,
  session_stats: stats,
  summary_exists: summaryText.includes('archive_count: 32'),
  manifest_exact: manifestText.length === 32 && manifestText.every((line, i) => line === `archive-${String(i + 1).padStart(2, '0')}=${fingerprints[i]}`),
  manifest_line_count: manifestText.length,
  key_preserved_in_summary: summaryText.includes(secret),
  recovery_exact_match: recoveryText.includes(secret),
  recovery_text: recoveryText.slice(0, 200),
  test_exit_code: test.exitCode,
  test_output: test.output,
  files: fs.readdirSync(workspace).sort(),
  events,
};
fs.appendFileSync(outFile, `${JSON.stringify(record)}\n`);
console.log(JSON.stringify(record, null, 2));
session.dispose();
if (record.source_tree_dirty || !record.summary_exists || !record.manifest_exact || !record.key_preserved_in_summary || !record.recovery_exact_match || record.test_exit_code !== 0 || record.compaction_event_count === 0) process.exitCode = 2;
