"""Build the README figures as standalone SVG files.

Every number comes from docs/RESULTS.md; the section is named beside each table.
Each SVG carries its own surface and adapts to the reader's color scheme.

Usage: python docs/figures/build_figures.py
"""
from __future__ import annotations

import math
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent
WIDTH = 960
PAD = 32

STYLE = """
text{font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;fill:#0b0b0b;font-size:14px}
.bg{fill:#fcfcfb}.edge{fill:none;stroke:#0b0b0b;stroke-opacity:.1}
.card{fill:#f9f9f7;stroke:#c3c2b7}
.title{font-size:22px;font-weight:600}.hero{font-size:36px;font-weight:600}.big{font-size:30px;font-weight:600}
.val{font-size:20px;font-weight:600}.strong{font-weight:600}.sub,.sub tspan{fill:#52514e}.mute{fill:#898781;font-size:12px}.foot{fill:#52514e;font-size:12px}
.tick{fill:#898781;font-size:12px;font-variant-numeric:tabular-nums}.num{font-variant-numeric:tabular-nums}
.inv{fill:#fff;font-size:12px;font-weight:600}
.blue{fill:#2a78d6}.orange{fill:#eb6834}.gray{fill:#898781}.empty{fill:#f0efec}.band{fill:#2a78d6;fill-opacity:.1}
.ring{stroke:#fcfcfb;stroke-width:2}
.grid{stroke:#e1e0d9}.axis{stroke:#c3c2b7}.link{stroke:#898781;stroke-width:2;stroke-linecap:round}
.arrow{stroke:#52514e;stroke-width:1.5;fill:none}.head{fill:#52514e}.check{stroke:#fff;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}
@media (prefers-color-scheme:dark){
text{fill:#f0efec}
.bg{fill:#1a1a19}.edge{stroke:#fff}
.card{fill:#0d0d0d;stroke:#383835}
.sub,.sub tspan,.foot{fill:#c3c2b7}
.blue{fill:#3987e5}.orange{fill:#d95926}.empty{fill:#383835}.band{fill:#3987e5}
.ring{stroke:#1a1a19}
.grid{stroke:#2c2c2a}.axis{stroke:#383835}
.arrow{stroke:#c3c2b7}.head{fill:#c3c2b7}
.inv{fill:#fff}.mute,.tick{fill:#898781}
}
"""


def wilson(passes: int, total: int, z: float = 1.959964) -> tuple[float, float]:
    rate = passes / total
    denominator = 1 + z * z / total
    centre = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return centre - margin, centre + margin


def text(x: float, y: float, value: str, cls: str = "", anchor: str = "start") -> str:
    attrs = f' class="{cls}"' if cls else ""
    if anchor != "start":
        attrs += f' text-anchor="{anchor}"'
    return f'<text x="{x:.1f}" y="{y:.1f}"{attrs}>{escape(value)}</text>'


def line(x1: float, y1: float, x2: float, y2: float, cls: str) -> str:
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="{cls}"/>'


def dot(x: float, y: float, cls: str, radius: float = 7) -> str:
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" class="{cls} ring"/>'


def bar(x: float, y: float, width: float, height: float, cls: str) -> str:
    """Horizontal bar: square at the baseline, 4px rounded at the data end."""
    r = min(4, width)
    end = x + width
    return (
        f'<path class="{cls}" d="M{x:.1f} {y:.1f}H{end - r:.1f}Q{end:.1f} {y:.1f} {end:.1f} {y + r:.1f}'
        f'V{y + height - r:.1f}Q{end:.1f} {y + height:.1f} {end - r:.1f} {y + height:.1f}H{x:.1f}Z"/>'
    )


def legend(x: float, y: float, entries: list[tuple[str, str]]) -> str:
    parts = []
    for cls, label in entries:
        parts.append(f'<rect x="{x:.1f}" y="{y - 10:.1f}" width="12" height="12" rx="3" class="{cls}"/>')
        parts.append(text(x + 18, y, label, "sub"))
        x += 18 + 7.4 * len(label) + 24
    return "".join(parts)


def figure(name: str, height: int, title: str, subtitle: str, foot: str, body: list[str]) -> None:
    header = text(PAD, 44, title, "title") + text(PAD, 70, subtitle, "sub")
    footer = text(PAD, height - 18, foot, "foot") if foot else ""
    write(name, height, f"{title}. {subtitle}", header + "".join(body) + footer)


def write(name: str, height: int, label: str, content: str) -> None:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" '
        f'width="{WIDTH}" height="{height}" role="img" aria-label="{escape(label, quote=True)}">'
        f"<title>{escape(label)}</title><style>{STYLE}</style>"
        f'<rect class="bg" width="{WIDTH}" height="{height}" rx="14"/>'
        f'<rect class="edge" x=".5" y=".5" width="{WIDTH - 1}" height="{height - 1}" rx="14"/>'
        f"{content}</svg>\n"
    )
    (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")


# Section 12: 1 = first attempt, F = rescued by the retry, 0 = failed.
OUTCOMES = {
    "X-think": {
        "cont_path": "111", "cont_quote": "FFF", "js_plural": "111", "js_sign": "111",
        "mcp_header": "111", "mcp_params": "111", "py_query": "1FF", "py_range": "000",
        "recover_date": "110", "recover_decode": "111", "tests_query": "0F1", "tests_range": "F0F",
    },
    "R-q4": {
        "cont_path": "111", "cont_quote": "111", "js_plural": "111", "js_sign": "111",
        "mcp_header": "111", "mcp_params": "111", "py_query": "111", "py_range": "000",
        "recover_date": "000", "recover_decode": "111", "tests_query": "1FF", "tests_range": "101",
    },
    "R-q6": {
        "cont_path": "F11", "cont_quote": "111", "js_plural": "010", "js_sign": "111",
        "mcp_header": "111", "mcp_params": "111", "py_query": "F1F", "py_range": "000",
        "recover_date": "010", "recover_decode": "111", "tests_query": "1F1", "tests_range": "01F",
    },
    # Section 11.
    "T5-rtk": {
        "cont_path": "010", "cont_quote": "110", "js_plural": "111", "js_sign": "001",
        "mcp_header": "111", "mcp_params": "111", "py_query": "000", "py_range": "000",
        "recover_date": "000", "recover_decode": "111", "tests_query": "000", "tests_range": "010",
    },
}


def count(arm: str, outcome: str) -> int:
    return sum(cell.count(outcome) for cell in OUTCOMES[arm].values())


def hero() -> None:
    body = [
        text(PAD, 66, "Local LLM Lab", "hero"),
        text(PAD, 98, "Testing how well a small AI model can work on code, using one home graphics card.", "sub"),
    ]
    stack = [("MODEL", "Qwen3.5-4B"), ("SERVER", "llama.cpp"), ("AGENT", "OpenCode"), ("GRAPHICS CARD", "RTX 3070, 8 GB")]
    for index, (label, value) in enumerate(stack):
        x = PAD + index * 224
        body.append(text(x, 146, label, "mute"))
        body.append(text(x, 172, value, "val"))
    write("hero", 204, "Local LLM Lab: Qwen3.5-4B, llama.cpp and OpenCode on an RTX 3070 with 8 GB", "".join(body))


def card(x: float, y: float, width: float, height: float, lines: list[tuple[str, str]]) -> str:
    parts = [f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="10" class="card"/>']
    baseline = y + height / 2 - (len(lines) - 1) * 10 + 5
    for index, (value, cls) in enumerate(lines):
        parts.append(text(x + width / 2, baseline + index * 20, value, cls, "middle"))
    return "".join(parts)


def arrow(points: list[tuple[float, float]], both: bool = False) -> str:
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    start = ' marker-start="url(#tip)"' if both else ""
    return f'<polyline points="{path}" class="arrow" marker-end="url(#tip)"{start}/>'


def pipeline() -> None:
    top, card_height, lower = 104, 92, 244
    body = [
        (
            '<defs><marker id="tip" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" '
            'orient="auto-start-reverse"><path d="M0 0L8 4L0 8Z" class="head"/></marker></defs>'
        ),
        card(32, top, 150, card_height, [("Task", "strong"), ("Real repository", "sub"), ("with a seeded bug", "sub")]),
        card(216, top, 170, card_height, [("OpenCode agent", "strong"), ("Reads, edits, runs", "sub"), ("in a bubblewrap sandbox", "sub")]),
        card(430, top, 150, card_height, [("Visible test", "strong"), ("The agent can", "sub"), ("read this one", "sub")]),
        card(624, top, 150, card_height, [("Private oracle", "strong"), ("Never mounted,", "sub"), ("never in a prompt", "sub")]),
        card(808, top, 120, card_height, [("Score", "strong"), ("Pass or fail", "sub")]),
        card(136, lower, 196, card_height, [("llama-server", "strong"), ("Qwen3.5-4B on the GPU", "sub"), ("outside the sandbox", "sub")]),
        card(430, lower, 190, card_height, [("One retry", "strong"), ("Same task, thinking on,", "sub"), ("temperature 0.6", "sub")]),
        arrow([(182, top + 46), (214, top + 46)]),
        arrow([(386, top + 46), (428, top + 46)]),
        arrow([(580, top + 46), (622, top + 46)]),
        arrow([(774, top + 46), (806, top + 46)]),
        arrow([(262, top + card_height), (262, lower - 2)], both=True),
        arrow([(505, top + card_height), (505, lower - 2)]),
        arrow([(430, lower + 46), (360, lower + 46), (360, top + card_height + 2)]),
        text(601, top + 36, "passes", "mute", "middle"),
        text(513, top + card_height + 28, "fails", "mute"),
        text(272, top + card_height + 28, "local API", "mute"),
    ]
    figure(
        "pipeline", 382,
        "How one episode is scored",
        "The agent works alone. A hidden test decides the result after the attempt ends.",
        "", body,
    )


def cascade() -> None:
    rows = [
        ("Control with thinking retry", 22, 30, "p = 0.008"),
        ("Recommended: Q4_K_M, MTP, checkpoints", 27, 29, "p = 1.0 vs control"),
        ("Same profile with Q6_K_L", 23, 28, "p = 0.69 vs control"),
        ("RTK output filter, no retry", 17, 17, "p = 0.23 vs control"),
    ]
    assert count("X-think", "1") == 22 and count("R-q4", "1") == 27 and count("R-q6", "1") == 23
    assert count("T5-rtk", "1") == 17
    assert count("X-think", "F") == 8 and count("R-q4", "F") == 2 and count("R-q6", "F") == 5

    left, right = 330, 740
    top, step = 128, 52
    low, high = 40, 100

    def scale(passes: float) -> float:
        return left + (passes / 36 * 100 - low) / (high - low) * (right - left)

    body = [legend(PAD, 102, [("blue", "first attempt"), ("orange", "after the retry")])]
    bottom = top + step * len(rows) - 18
    for tick in range(low, high + 1, 20):
        x = left + (tick - low) / (high - low) * (right - left)
        body.append(line(x, top - 18, x, bottom, "grid"))
        body.append(text(x, bottom + 20, f"{tick}%", "tick", "middle"))
    for index, (label, first, final, note) in enumerate(rows):
        y = top + index * step
        body.append(text(PAD, y + 5, label))
        if final > first:
            body.append(line(scale(first), y, scale(final), y, "link"))
            body.append(dot(scale(final), y, "orange"))
        body.append(dot(scale(first), y, "blue"))
        outcome = f"{first} → {final} of 36" if final > first else f"{first} of 36"
        body.append(text(right + 24, y, outcome, "strong num"))
        body.append(text(right + 24, y + 17, note, "mute"))
    figure(
        "retry-with-thinking", 372,
        "One retry with thinking is the only confirmed gain",
        "Pass rate of 36 paired episodes. The axis starts at 40%.",
        "Exact McNemar tests. Sections 11 and 12 of docs/RESULTS.md.", body,
    )


def one_factor() -> None:
    rows = [
        ("Control", "64K context, KV q4_0, Q4_K_M", 16, 24, "blue"),
        ("Context 16K", "ends in context errors", 3, 12, "orange"),
        ("Context 32K", "", 9, 12, "gray"),
        ("Context 128K", "", 9, 12, "gray"),
        ("KV q8_0", "", 9, 12, "gray"),
        ("KV f16", "", 7, 12, "gray"),
        ("Weights Q6_K", "", 10, 12, "gray"),
        ("Weights Q8_0", "", 8, 12, "gray"),
        ("Prompt cache off", "", 9, 12, "gray"),
        ("Thinking on", "", 11, 12, "gray"),
    ]
    assert [round(100 * bound) for bound in wilson(16, 24)] == [47, 82]
    assert [round(100 * bound) for bound in wilson(3, 12)] == [9, 53]

    left, right = 300, 840
    top, step = 128, 30

    def scale(rate: float) -> float:
        return left + rate * (right - left)

    bottom = top + step * len(rows) - 10
    low, high = wilson(16, 24)
    body = [
        (
            f'<rect x="{scale(low):.1f}" y="{top - 22}" width="{scale(high) - scale(low):.1f}" '
            f'height="{bottom - top + 22}" class="band"/>'
        ),
        text((scale(low) + scale(high)) / 2, top - 30, "control's 95% interval", "mute", "middle"),
    ]
    for tick in range(0, 101, 25):
        x = scale(tick / 100)
        body.append(line(x, top - 22, x, bottom, "grid"))
        body.append(text(x, bottom + 20, f"{tick}%", "tick", "middle"))
    for index, (label, note, passes, total, cls) in enumerate(rows):
        y = top + index * step
        body.append(text(PAD, y + 5, label, "strong" if cls != "gray" else ""))
        if note:
            body.append(text(PAD + 8.6 * len(label) + 8, y + 5, note, "mute"))
        low, high = wilson(passes, total)
        body.append(line(scale(low), y, scale(high), y, "link"))
        body.append(dot(scale(passes / total), y, cls))
        body.append(text(right + 24, y + 5, f"{passes}/{total}", "num"))
    figure(
        "one-factor", 486,
        "Most single settings stay inside the noise",
        "First-attempt pass rate with 95% Wilson intervals, stages 1 to 3.",
        "Only 16K context falls clearly lower. No arm reaches p < 0.05 with 12 pairs. Section 2 of docs/RESULTS.md.",
        body,
    )


def task_grid() -> None:
    arms = ["X-think", "R-q4", "R-q6", "T5-rtk"]
    titles = {"X-think": "Control + retry", "R-q4": "Recommended", "R-q6": "With Q6_K_L", "T5-rtk": "RTK filter"}
    tasks = sorted(
        OUTCOMES["X-think"],
        key=lambda task: (-sum(len(c) - c.count("0") for c in (OUTCOMES[a][task] for a in arms)), task),
    )
    left, top, cell, gap, group = 190, 136, 46, 4, 36
    height = 24
    body = [legend(PAD, 102, [("blue", "first attempt"), ("orange", "rescued by the retry"), ("empty", "failed")])]
    for arm_index, arm in enumerate(arms):
        x = left + arm_index * (3 * cell + 2 * gap + group)
        body.append(text(x + (3 * cell + 2 * gap) / 2, top - 12, titles[arm], "strong", "middle"))
    for row, task in enumerate(tasks):
        y = top + row * (height + gap)
        body.append(text(PAD, y + 17, task, "num"))
        for arm_index, arm in enumerate(arms):
            x0 = left + arm_index * (3 * cell + 2 * gap + group)
            for repetition, outcome in enumerate(OUTCOMES[arm][task]):
                x = x0 + repetition * (cell + gap)
                cls = {"1": "blue", "F": "orange", "0": "empty"}[outcome]
                body.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{height}" rx="4" class="{cls}"/>')
                if outcome == "1":
                    body.append(f'<path class="check" d="M{x + 18} {y + 12}l4 4l7 -8"/>')
                elif outcome == "F":
                    body.append(text(x + cell / 2, y + 16, "R", "inv", "middle"))
    figure(
        "task-outcomes", 508,
        "The 12-task corpus saturates, so corpus v2 adds 24 tasks",
        "Each square is one run, and every task ran three times per setup. py_range never passed.",
        "Sections 11 and 12 of docs/RESULTS.md.", body,
    )


def latency() -> None:
    rows = [
        ("Agent episode, stage 3", 7.498, 0.296),
        ("46K prefix, T3b v2", 16.1, 0.158),
        ("46K prefix, T3b v3", 17.8, 2.1),
    ]
    left, right = 230, 840
    top, step = 128, 66

    def scale(seconds: float) -> float:
        return (right - left) * seconds / 20

    body = [legend(PAD, 102, [("gray", "no cached prefix"), ("blue", "cached prefix")])]
    bottom = top + step * len(rows) - 14
    for tick in range(0, 21, 5):
        x = left + scale(tick)
        body.append(line(x, top - 10, x, bottom, "grid"))
        body.append(text(x, bottom + 20, f"{tick} s", "tick", "middle"))
    for index, (label, cold, warm) in enumerate(rows):
        y = top + index * step
        body.append(text(PAD, y + 22, label))
        body.append(bar(left, y, scale(cold), 22, "gray"))
        body.append(bar(left, y + 24, max(scale(warm), 3), 22, "blue"))
        body.append(text(left + scale(cold) + 8, y + 16, f"{cold:.1f} s", "num"))
        body.append(text(left + max(scale(warm), 3) + 8, y + 40, f"{warm:.2f} s".replace("2.10", "2.1"), "strong num"))
    figure(
        "prompt-cache", 372,
        "Prompt cache cuts time to first token by 8 to 100 times",
        "Median time to first token. The pass rate showed no detectable change.",
        "Sections 2 and 10 of docs/RESULTS.md.", body,
    )


def vram() -> None:
    rows = [
        ("Control", 4567, "gray"),
        ("Context 128K", 5422, "gray"),
        ("KV f16", 5754, "gray"),
        ("Recommended", 5800, "blue"),
        ("Weights Q8_0", 6033, "gray"),
        ("Recommended, Q6_K_L", 6618, "gray"),
    ]
    left, right = 230, 872
    top, step = 116, 36
    limit = 8192

    def scale(mib: float) -> float:
        return (right - left) * mib / limit

    bottom = top + step * len(rows) - 8
    body = []
    for tick in range(0, 8001, 2000):
        x = left + scale(tick)
        body.append(line(x, top - 12, x, bottom, "grid"))
        body.append(text(x, bottom + 20, f"{tick // 1000}K" if tick else "0", "tick", "middle"))
    edge = left + scale(limit)
    body.append(line(edge, top - 12, edge, bottom, "axis"))
    body.append(text(edge, top - 20, "8,192 MiB card limit", "mute", "end"))
    for index, (label, mib, cls) in enumerate(rows):
        y = top + index * step
        body.append(text(PAD, y + 17, label, "strong" if cls == "blue" else ""))
        body.append(bar(left, y, scale(mib), 24, cls))
        body.append(text(left + scale(mib) + 8, y + 17, f"{mib:,}", "strong num" if cls == "blue" else "num"))
    figure(
        "vram", 382,
        "The recommended profile leaves about 2.4 GB free",
        "Peak VRAM in MiB for the whole device, including the Windows desktop.",
        "Sections 2 and 12 of docs/RESULTS.md.", body,
    )


def long_tasks() -> None:
    rows = [
        ("Large context (128K)", 9, 7.87),
        ("Headroom (32K)", 7, 2.41),
        ("OpenCode compaction (32K)", 6, 1.52),
        ("Reset with PROGRESS.md (32K)", 5, 2.01),
    ]
    first, second = 256, 620
    width = 236
    top, step = 134, 42
    body = [text(first, 112, "Hidden tests passed, of 9", "strong"), text(second, 112, "Prompt tokens, millions", "strong")]
    for index, (label, passed, tokens) in enumerate(rows):
        y = top + index * step
        body.append(text(PAD, y + 17, label))
        body.append(bar(first, y, width * passed / 9, 24, "blue"))
        body.append(text(first + width * passed / 9 + 8, y + 17, str(passed), "num"))
        body.append(bar(second, y, width * tokens / 8, 24, "gray"))
        body.append(text(second + width * tokens / 8 + 8, y + 17, f"{tokens:.2f}", "num"))
    body.append(line(first, top - 8, first, top + step * len(rows) - 12, "axis"))
    body.append(line(second, top - 8, second, top + step * len(rows) - 12, "axis"))
    figure(
        "long-tasks", 340,
        "Long tasks favour a large context, at a token cost",
        "Two marathons of 5 and 6 objectives, one repetition per approach.",
        "A first read, not a confirmed ranking. Section 9 of docs/RESULTS.md.", body,
    )


def main() -> None:
    hero()
    pipeline()
    cascade()
    one_factor()
    task_grid()
    latency()
    vram()
    long_tasks()


if __name__ == "__main__":
    main()
