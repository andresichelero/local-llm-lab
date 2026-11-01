# Test E0: decode speed at each power limit and memory clock. Run it from an ordinary
# PowerShell with no other GPU load. Each point needs the setting changed by hand in
# MSI Afterburner, then Enter; it takes about two minutes. Press s to skip a point.
$ErrorActionPreference = 'Stop'
$repo = '/mnt/d/Usuario/Downloads/LLM/.worktrees/translate-en'
$lab = '/home/foxtrot/local-llm-benchmark'
$python = "$lab/envs/lab-validation-20261028/bin/python"
$points = @(
    @{ name = 'p220'; ask = 'Power Limit 100% (220 W), memory offset 0' },
    @{ name = 'p200'; ask = 'Power Limit 91% (200 W), memory offset 0' },
    @{ name = 'mem-minus-200'; ask = 'Power Limit 109% (240 W), memory offset -200' },
    @{ name = 'mem-plus-200'; ask = 'Power Limit 109% (240 W), memory offset +200' },
    @{ name = 'control'; ask = 'Power Limit 109% (240 W), memory offset 0' }
)
foreach ($point in $points) {
    $answer = Read-Host "Set $($point.ask), click Apply, then press Enter (s to skip)"
    if ($answer -eq 's') { continue }
    $out = "$lab/results/e0-20261031/$($point.name)"
    wsl -e bash -c "builtin cd $repo && PYTHONDONTWRITEBYTECODE=1 $python -m benchmark.decode_probe --arms base --blocks 2 --repeats 3 --out $out 2>&1 | grep -E 'limit=|Error|error'"
}
"Done. Leave Afterburner at the settings you normally use."
