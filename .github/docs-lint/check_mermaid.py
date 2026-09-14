"""Mermaid checks for README.md and docs/, run by .github/workflows/docs.yml.

GitHub draws every mermaid block in the reader's browser with its own Mermaid,
in Mermaid's default theme for light mode and its dark theme for dark mode. A
diagram that pins a theme looks right in one mode and loses its arrows in the
other, and a block that does not parse shows an error instead of a diagram.

    python .github/docs-lint/check_mermaid.py rules
        Plain Python, no Node, so it runs locally too. Refuses frontmatter,
        %%{init}%% directives, themeVariables, linkStyle and architecture-beta;
        a classDef without color:; an unquoted flowchart node or edge label;
        a diagram without accTitle and accDescr; and diagram source left
        outside a mermaid fence, which GitHub shows as plain text.

    python .github/docs-lint/check_mermaid.py version
        Renders an info diagram and requires the version it draws to be the one
        pinned in package.json overrides: the version pinned as GitHub's when
        GitHub's version was last read. CI cannot read GitHub's live version.

    python .github/docs-lint/check_mermaid.py canary
        Renders canary.broken.mmd and requires a parse error, so the render gate
        is seen to fail before it is trusted to pass. That file is deliberately
        broken and byte-identical to mermaid-cli 11.17.0's
        test-negative/invalid.expect-error.mmd, whose failure its own tests
        assert. Do not fix it, comment it or move it into docs/.

    python .github/docs-lint/check_mermaid.py render --out DIR
        Renders every block in both themes into DIR and annotates each failure
        at the Markdown file and line where the block opens.

version, canary and render need npm ci in .github/docs-lint. CI runs them under
aa-exec --profile=chrome so Chromium keeps its sandbox.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MMDC = HERE / "node_modules" / ".bin" / "mmdc"
CONFIG = HERE / "mermaid-github.json"
CANARY = HERE / "canary.broken.mmd"
# Mermaid theme GitHub picks for each mode, and the page colour behind it.
THEMES = {"default": "#ffffff", "dark": "#0d1117"}

FENCE = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[^\s`]*)")
QUOTED = re.compile(r'"[^"\n]*"')
NODE = re.compile(
    r"(?<![\w\"-])[A-Za-z_]\w*(?:-\w+)*[ \t]*"
    r"(?P<open>\(\[|\[\[|\[\(|\(\(\(|\(\(|\{\{|\[/|\[\\|\(|\[|\{|>)[ \t]*(?P<after>.?)"
)
EDGE_LABEL = re.compile(r"(?:--|==|-\.)[-.=>ox]*[ \t]*\|(?P<label>[^|\n]*)\|")
NOT_A_SHAPE = ("%%", "accTitle", "accDescr", "classDef", "class ", "style ", "click ",
               "linkStyle", "direction ")
# The first line of a flowchart, or an accessible title, where prose should be.
STRAY = re.compile(r"^[ \t]{0,3}(?:(?:flowchart|graph)[ \t]+(?:TB|TD|BT|RL|LR)\b|accTitle[ \t]*:)")


@dataclass
class Block:
    source: str
    line: int
    text: str

    @property
    def name(self) -> str:
        return f"{self.source.replace('/', '__')}-L{self.line}"


def markdown_files(root: Path) -> list[Path]:
    """README.md and every docs/**/*.md that exists, in a stable order."""
    return [path for path in [root / "README.md", *sorted((root / "docs").rglob("*.md"))]
            if path.is_file()]


def closes(fence: str, line: str) -> bool:
    return re.match(rf"^[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$", line) is not None


def blocks(root: Path) -> list[Block]:
    """Every fenced mermaid block in README.md and docs/**/*.md, with its fence line."""
    found = []
    for path in markdown_files(root):
        lines = path.read_text(encoding="utf-8").splitlines()
        index = 0
        while index < len(lines):
            opened = FENCE.match(lines[index])
            if not opened:
                index += 1
                continue
            fence, start, indent = opened.group("fence"), index + 1, len(opened.group("indent"))
            body = []
            index += 1
            while index < len(lines) and not closes(fence, lines[index]):
                line = lines[index]
                body.append(line[indent:] if not line[:indent].strip() else line)
                index += 1
            index += 1
            if opened.group("info") == "mermaid":
                source = path.relative_to(root).as_posix()
                found.append(Block(source, start, "\n".join(body) + "\n"))
    return found


def stray_diagram_lines(root: Path) -> list[tuple[str, int]]:
    """(file, line) for diagram source outside every fence, which no other check reads."""
    found = []
    for path in markdown_files(root):
        fence = ""
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if fence:
                if closes(fence, line):
                    fence = ""
                continue
            opened = FENCE.match(line)
            if opened:
                fence = opened.group("fence")
            elif STRAY.match(line):
                found.append((path.relative_to(root).as_posix(), number))
    return found


def unquoted_labels(lines: list[str]) -> list[tuple[int, str]]:
    found = []
    describing = False
    for number, raw in enumerate(lines, 1):
        text = raw.strip()
        if describing:
            describing = "}" not in text
            continue
        if re.match(r"accDescr\s*\{", text):
            describing = "}" not in text
            continue
        if not text or text.startswith(NOT_A_SHAPE):
            continue
        bare = QUOTED.sub('""', text)
        if any(match.group("after") != '"' for match in NODE.finditer(bare)):
            found.append((number, ('quote every node label, as Id["Label"], so punctuation '
                                   "cannot break the parse")))
        elif any(match.group("label").strip() != '""' for match in EDGE_LABEL.finditer(bare)):
            found.append((number, 'quote every edge label, as -->|"label"|'))
    return found


def violations(block: Block) -> list[tuple[int, str]]:
    """(line within the block, reason) for each rule the block breaks."""
    lines = block.text.splitlines()
    meaningful = [(number, raw.strip()) for number, raw in enumerate(lines, 1)
                  if raw.strip() and not raw.strip().startswith("%%")]
    if not meaningful:
        return [(1, "the block is empty")]
    first_line, first = meaningful[0]
    found = []
    if first == "---":
        found.append((first_line, "frontmatter config can pin one theme for both GitHub modes"))
    kind = first.split()[0]
    if kind == "architecture-beta":
        found.append((first_line, ("architecture-beta icons show as placeholders on GitHub, "
                                   "so draw a flowchart")))
    for number, raw in enumerate(lines, 1):
        text = raw.strip()
        if "%%{" in text:
            found.append((number, "an init directive can pin one theme for both GitHub modes"))
        if "themeVariables" in text:
            found.append((number, "themeVariables pin one look for both GitHub modes"))
        if re.match(r"linkStyle\b", text):
            found.append((number, "linkStyle fixes an edge colour that fades on one GitHub canvas"))
        if re.match(r"classDef\b", text) and not re.search(r"(?:^|[\s,;])color\s*:", text):
            found.append((number, ("a classDef without color: leaves label text to the theme, "
                                   "which is too faint on the fill")))
    if not any(re.match(r"accTitle\s*:", text) for _, text in meaningful):
        found.append((first_line, "no accTitle, so a screen reader has no name for the diagram"))
    if not any(re.match(r"accDescr\s*[:{]", text) for _, text in meaningful):
        found.append((first_line, "no accDescr, so a screen reader has no description of it"))
    if kind in ("flowchart", "graph"):
        found += unquoted_labels(lines)
    return found


def rules(root: Path) -> int:
    found = blocks(root)
    if not found:
        print("::error::no mermaid blocks in README.md or docs/, so there is nothing to check")
        return 1
    broken = 0
    for block in found:
        for offset, reason in violations(block):
            broken += 1
            print(f"::error file={block.source},line={block.line + offset}::{reason}")
    for source, line in stray_diagram_lines(root):
        broken += 1
        print(f"::error file={source},line={line}::diagram source outside a mermaid fence is "
              "shown as plain text, and no render or rule check reads it")
    print(f"{len(found)} mermaid blocks, {broken} rule violations")
    return 1 if broken else 0


def mmdc(command: list[str], source: Path, output: Path, theme: str = "default"):
    try:
        return subprocess.run(
            [*command, "-q", "-c", str(CONFIG), "-t", theme, "-b", THEMES[theme],
             "-i", str(source), "-o", str(output)],
            capture_output=True, text=True, timeout=180,
        )
    except FileNotFoundError:
        print(f"::error::{command[0]} not found, so run npm ci in .github/docs-lint first")
        raise SystemExit(1) from None
    except subprocess.TimeoutExpired as expired:
        return subprocess.CompletedProcess(expired.cmd, 124, "", "timed out after 180 seconds")


def tail(text: str, lines: int = 30) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def summarise(lines: list[str]) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n\n")


def installed_mermaid() -> list[str]:
    modules = HERE / "node_modules"
    manifests = [modules / "mermaid" / "package.json",
                 *modules.glob("**/node_modules/mermaid/package.json")]
    return sorted({json.loads(path.read_text(encoding="utf-8")).get("version", "?")
                   for path in manifests if path.is_file()})


def version(command: list[str]) -> int:
    want = json.loads((HERE / "package.json").read_text(encoding="utf-8"))["overrides"]["mermaid"]
    installed = installed_mermaid()
    drawn: list[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        info, svg = Path(scratch) / "info.mmd", Path(scratch) / "info.svg"
        info.write_text("info\n", encoding="utf-8")
        done = mmdc(command, info, svg)
        if done.returncode == 0 and svg.is_file():
            text = svg.read_text(encoding="utf-8")
            drawn = sorted(set(re.findall(r">v(\d+\.\d+\.\d+[^<]*)<", text)))
    print(f"pinned {want}; installed {installed}; drawn by the renderer {drawn}")
    if done.returncode != 0:
        print(tail(done.stdout + done.stderr))
        print("::error::the info diagram did not render, so the version in use is unknown")
        return 1
    if installed != [want] or drawn != [want]:
        print(f"::error::the pin is Mermaid {want}, GitHub's version when it was last read, "
              f"but this run installed {installed} and drew {drawn}")
        return 1
    summarise([f"Mermaid in this run: {want}, the version pinned as GitHub's."])
    return 0


def canary(command: list[str]) -> int:
    with tempfile.TemporaryDirectory() as scratch:
        done = mmdc(command, CANARY, Path(scratch) / "canary.svg")
    said = done.stdout + done.stderr
    if done.returncode == 0:
        print("::error::a deliberately broken diagram rendered, so the render gate cannot fail")
        return 1
    if "Parse error" not in said:
        print(tail(said))
        print("::error::the broken diagram failed for a reason other than parsing (install, "
              "browser or sandbox), so this run proves nothing about parsing")
        return 1
    refusal = next(line for line in said.splitlines() if "Parse error" in line).strip()
    print(f"refused as it should be: {refusal}")
    summarise([f"Broken diagram refused: `{refusal}`"])
    return 0


def render(root: Path, command: list[str], out: Path) -> int:
    found = blocks(root)
    if not found:
        print("::error::no mermaid blocks in README.md or docs/, so there is nothing to render")
        return 1
    (out / "svg").mkdir(parents=True, exist_ok=True)
    rows = ["| Block | default | dark |", "| --- | --- | --- |"]
    failed = 0
    for block in found:
        source = out / f"{block.name}.mmd"
        source.write_text(block.text, encoding="utf-8", newline="\n")
        results = []
        for theme in THEMES:
            done = mmdc(command, source, out / "svg" / f"{block.name}-{theme}.svg", theme)
            results.append("renders" if done.returncode == 0 else "FAILS")
            if done.returncode != 0:
                failed += 1
                print(f"::error file={block.source},line={block.line}::this mermaid block does "
                      f"not render in the {theme} theme")
                print(tail(done.stdout + done.stderr))
        rows.append(f"| {block.source}:{block.line} | {results[0]} | {results[1]} |")
    summarise(rows)
    print(f"{len(found)} mermaid blocks, {2 * len(found)} renders, {failed} failed")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mermaid checks for README.md and docs/.")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root to read")
    parser.add_argument("--mmdc", help="command that runs mermaid-cli (default: the pinned one)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("rules")
    commands.add_parser("version")
    commands.add_parser("canary")
    commands.add_parser("render").add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    command = shlex.split(args.mmdc) if args.mmdc else [str(MMDC)]
    if args.command == "rules":
        return rules(args.root)
    if args.command == "version":
        return version(command)
    if args.command == "canary":
        return canary(command)
    return render(args.root, command, args.out)


if __name__ == "__main__":
    sys.exit(main())
