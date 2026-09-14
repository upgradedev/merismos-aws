"""Nothing in this repository checked that a link in the README or docs led anywhere.

Moving a section from README.md into docs/ changes the base of every relative
path in it and orphans every anchor that pointed at its heading. GitHub shows
the result only as a 404 or a page that does not scroll. This resolves every
link offline, the way GitHub would:

- the target exists with exactly that spelling, because paths on GitHub are
  case-sensitive and Windows and macOS checkouts are not;
- git does not ignore it, so it is published with the commit;
- a #fragment is an anchor GitHub makes from a heading in the target, and an
  #L line anchor points at a line the file has.

Links into this repository written as github.com URLs are resolved like
relative ones, in the docs and in the app's own source. Other URLs are not
fetched: this suite refuses sockets.

The shipped app also sends readers to README sections by name ("see Cost and
sustainability in the README"). Each name it uses must still be a README heading.
"""

from __future__ import annotations

import os
import re
import subprocess
import unicodedata
from functools import cache
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
APP = sorted(path for path in (ROOT / "frontend" / "src").rglob("*")
             if path.suffix in {".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".json", ".md"})

TICK = "`"
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
ATX = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
SETEXT = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
NOT_PARAGRAPH = re.compile(r"^(?:\s*(?:[-*+>|<]|\d+[.)])|\s{4})")
CODE_SPAN = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)")
INLINE = re.compile(r"\]\(\s*(<[^>\n]*>|[^)\s]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
# A reference definition, but not a footnote definition such as [^1]: text.
DEFINITION = re.compile(r"^ {0,3}\[(?!\^)[^\]]+\]:[ \t]*(<[^>\n]*>|\S+)")
ATTRIBUTE = re.compile(r"\b(?:href|src)\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
HTML_ANCHOR = re.compile(r"<a\s[^>]*\b(?:name|id)\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
SCHEME = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.IGNORECASE)
LINE_ANCHOR = re.compile(r"L(\d+)(?:-L(\d+))?")
# "see Cost and sustainability in the README" in the app's copy. The name must
# start with a capital, so no cited name can slug to the empty string.
CITED = re.compile(r"\b[Ss]ee ([A-Z][^.;:'\"`<>{}\n]*?) in the README\b")

GITHUB = r"https://github\.com/upgradedev/merismos-aws"
RAW = r"https://raw\.githubusercontent\.com/upgradedev/merismos-aws"
TAIL = r"(?P<query>\?[^#]*)?(?:#(?P<fragment>.*))?$"
REPOSITORY_URL = re.compile(rf"(?:{GITHUB}|{RAW})[^\s<>\"'`()\[\]]*", re.IGNORECASE)
INTO_REPOSITORY = [
    # (pattern, fixed path or None, prefix for the captured path). Anything else under the
    # repository URL (actions/runs, issues, a commit) is a page, not a file, and is left alone.
    (re.compile(rf"^{GITHUB}/(?:blob|tree)/main/(?P<path>[^?#]*){TAIL}", re.I), None, ""),
    (re.compile(rf"^{RAW}/(?:refs/heads/)?main/(?P<path>[^?#]*){TAIL}", re.I), None, ""),
    (re.compile(rf"^{GITHUB}/actions/workflows/(?P<path>[^/?#]+)(?:/badge\.svg)?{TAIL}", re.I),
     None, ".github/workflows/"),
    (re.compile(rf"^{GITHUB}/?{TAIL}", re.I), "README.md", ""),
]


def slug(heading: str) -> str:
    """GitHub's anchor for a heading's text, before a repeat gets its -1, -2 suffix."""
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", "", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace(TICK, "")
    text = re.sub(r"(\*\*|__|\*)", "", text)
    text = text.strip().lower()
    text = "".join(c for c in text if unicodedata.category(c)[0] in "LMN" or c in "-_ ")
    return text.replace(" ", "-")


def unique(base: str, seen: dict[str, int]) -> str:
    """Number a repeated slug the way GitHub does: foo, foo-1, foo-2."""
    name = base
    while name in seen:
        seen[base] += 1
        name = f"{base}-{seen[base]}"
    seen[name] = 0
    return name


def _closes(match: re.Match[str], fence: str) -> bool:
    marker, rest = match.group(1), match.group(2)
    return marker[0] == fence[0] and len(marker) >= len(fence) and not rest.strip()


def outside_fences(text: str):
    """(line number, line) for every line that is not inside a fenced code block."""
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        match = FENCE.match(line)
        if fence is not None:
            if match and _closes(match, fence):
                fence = None
        elif match and not (match.group(1)[0] == TICK and TICK in match.group(2)):
            fence = match.group(1)
        else:
            yield number, line


def anchors(text: str) -> set[str]:
    """Every fragment GitHub serves for a Markdown file: its headings and HTML anchors."""
    seen: dict[str, int] = {}
    found: set[str] = set()
    paragraph: list[str] = []
    previous = 0
    for number, line in outside_fences(text):
        if number != previous + 1:
            paragraph = []
        previous = number
        heading = None
        atx = ATX.match(line)
        if atx:
            heading, paragraph = atx.group(1) or "", []
        elif SETEXT.match(line) and paragraph:
            heading, paragraph = " ".join(paragraph), []
        elif not line.strip() or NOT_PARAGRAPH.match(line):
            paragraph = []
        else:
            paragraph.append(line.strip())
        if heading is not None:
            found.add(unique(slug(heading), seen))
    return found | set(HTML_ANCHOR.findall(text))


def links(text: str, markdown: bool = True):
    """(line number, target) for each link a reader could follow."""
    lines = outside_fences(text) if markdown else enumerate(text.splitlines(), 1)
    for number, line in lines:
        prose = CODE_SPAN.sub(" ", line) if markdown else line
        targets = [m.group(0).rstrip(".,;:!?") for m in REPOSITORY_URL.finditer(prose)]
        if markdown:
            for pattern in (INLINE, DEFINITION, ATTRIBUTE):
                targets += [m.group(1).strip("<>") for m in pattern.finditer(prose)]
        for target in dict.fromkeys(targets):
            yield number, target


def resolve(source: Path, root: Path, target: str) -> tuple[str, str, bool] | None:
    """(repository path, fragment, plain view) a link points at, or None if it leaves GitHub."""
    for pattern, fixed, prefix in INTO_REPOSITORY:
        match = pattern.match(target)
        if match:
            path = fixed or prefix + unquote(match.group("path")).strip("/")
            query, fragment = match.group("query") or "", match.group("fragment") or ""
            return path, unquote(fragment), "plain=1" in query
    if SCHEME.match(target):
        return None
    address, _, fragment = target.partition("#")
    address, _, query = address.partition("?")
    address = unquote(address)
    if address.startswith("/"):
        joined = address.lstrip("/")
    elif address:
        joined = f"{source.parent.relative_to(root).as_posix()}/{address}"
    else:
        joined = source.relative_to(root).as_posix()
    normal = os.path.normpath(joined).replace(os.sep, "/")
    return ("" if normal == "." else normal), unquote(fragment), "plain=1" in query


def exists_exactly(root: Path, relative: str) -> bool:
    """True only if every part of the path exists with exactly this spelling."""
    here = root
    for part in relative.split("/"):
        if not part:
            continue
        if not here.is_dir() or part not in os.listdir(here):
            return False
        here = here / part
    return True


@cache
def publishable(root: Path) -> frozenset[str] | None:
    """Files and folders git would publish (tracked, or new and not ignored), or None."""
    if not (root / ".git").exists():
        return None
    command = ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
               "--exclude-standard"]
    try:
        listed = subprocess.run(command, capture_output=True, check=True, timeout=120).stdout
        names = listed.decode("utf-8").split("\0")
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return None
    paths = set()
    for name in filter(None, names):
        parts = name.split("/")
        paths.update("/".join(parts[:end]) for end in range(1, len(parts) + 1))
    return frozenset(paths)


def fragment_problem(destination: Path, fragment: str, plain: bool,
                     known: dict[Path, set[str]]) -> str | None:
    fragment = fragment.removeprefix("user-content-")
    markdown = destination.suffix.lower() == ".md"
    lines = LINE_ANCHOR.fullmatch(fragment)
    if lines and (plain or not markdown):
        last = int(lines.group(2) or lines.group(1))
        count = len(destination.read_text(encoding="utf-8", errors="replace").splitlines())
        return None if last <= count else f"#{fragment} is past its last line, {count}"
    if not markdown:
        return None
    if destination not in known:
        known[destination] = anchors(destination.read_text(encoding="utf-8"))
    if fragment in known[destination]:
        return None
    return f"no heading in {destination.name} makes #{fragment}"


def link_problems(root: Path, sources: list[Path], markdown: bool = True,
                  published: frozenset[str] | None = None) -> list[str]:
    problems: list[str] = []
    known: dict[Path, set[str]] = {}
    for source in sources:
        for number, target in links(source.read_text(encoding="utf-8"), markdown):
            found = resolve(source, root, target)
            if found is None:
                continue
            relative, fragment, plain = found
            where = f"{source.relative_to(root).as_posix()}:{number} -> {target}"
            destination = root / relative
            if relative == ".." or relative.startswith("../"):
                problems.append(f"{where}: leaves the repository")
            elif not exists_exactly(root, relative):
                problems.append(f"{where}: no file or folder with exactly this name")
            elif published is not None and relative and relative not in published:
                problems.append(f"{where}: git ignores it, so GitHub never shows it")
            elif fragment and destination.is_file():
                problem = fragment_problem(destination, fragment, plain, known)
                if problem:
                    problems.append(f"{where}: {problem}")
    return problems


def test_the_slug_reproduces_the_anchors_github_generated():
    # Heading text at 9a0ba45 and the id GitHub gave it on the blob page, read 2026-09-14.
    observed = {
        "Merismos": "merismos",
        "Try one short flow": "try-one-short-flow",
        "Contents": "contents",
        "What is real and what is demonstrated": "what-is-real-and-what-is-demonstrated",
        "Architecture": "architecture",
        "Publication and recovery boundaries": "publication-and-recovery-boundaries",
        "Evidence and honest limits": "evidence-and-honest-limits",
        "Interpretation evaluation: source preparation, not measured model quality":
            "interpretation-evaluation-source-preparation-not-measured-model-quality",
        "Separately preregistered cited candidate (source preparation only)":
            "separately-preregistered-cited-candidate-source-preparation-only",
        "X1 HTTP correlation (source-only checkpoint, not cloud cost)":
            "x1-http-correlation-source-only-checkpoint-not-cloud-cost",
        "Current public acceptance": "current-public-acceptance",
        "Cost and sustainability": "cost-and-sustainability",
        "Run it locally": "run-it-locally",
        "Validation and release": "validation-and-release",
        "Pre-existing components and licences": "pre-existing-components-and-licences",
        "Merismos: AWS execution and trust boundaries":
            "merismos-aws-execution-and-trust-boundaries",
        "Runtime, not a platform claim": "runtime-not-a-platform-claim",
        "Governed agent and workflow flow": "governed-agent-and-workflow-flow",
        "Deployment and evidence": "deployment-and-evidence",
    }
    assert {heading: slug(heading) for heading in observed} == observed
    seen: dict[str, int] = {}
    assert [unique(slug("Limits"), seen) for _ in range(3)] == ["limits", "limits-1", "limits-2"]


def test_every_link_in_the_readme_and_the_docs_lands():
    published = publishable(ROOT)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        assert published is not None, "git listed nothing, so ignored targets went unchecked"
    problems = link_problems(ROOT, DOCS, published=published)
    assert not problems, "\n".join(problems)


def test_every_repository_link_in_the_app_source_lands():
    # No app file links into github.com/upgradedev/merismos-aws at 9a0ba45; this holds the
    # first one to the same standard as the docs.
    assert any(path.suffix == ".tsx" for path in APP), "found no app source, so checked nothing"
    problems = link_problems(ROOT, APP, markdown=False, published=publishable(ROOT))
    assert not problems, "\n".join(problems)


def test_every_readme_section_the_app_names_is_a_heading():
    # The shipped app says "see Cost and sustainability in the README", and it does not
    # change when the docs do.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    headings = {slug(match.group(1) or "") for _, line in outside_fences(readme)
                if (match := ATX.match(line))}
    cited = [(path, name) for path in APP if path.suffix in {".ts", ".tsx"}
             for name in CITED.findall(path.read_text(encoding="utf-8"))]
    assert cited, "found no README section named in the app source, so checked nothing"
    missing = [f"{path.relative_to(ROOT).as_posix()}: {name!r}" for path, name in cited
               if slug(name) not in headings]
    assert not missing, "\n".join(missing)


def test_the_checker_is_reading_links_at_all():
    readme = ROOT / "README.md"
    followed = [target for _, target in links(readme.read_text(encoding="utf-8"))
                if resolve(readme, ROOT, target) is not None]
    # A parser that stopped matching would let the two tests above pass on nothing.
    assert len(followed) >= 10, followed
    assert sum("#" in target for target in followed) >= 5, followed


def test_each_way_a_link_breaks_is_caught(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n\n## A heading\n\nOne\nTwo\n",
                                                encoding="utf-8")
    (tmp_path / "build.log").write_text("generated\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    repository = "https://github.com/upgradedev/merismos-aws"
    readme.write_text("\n".join([
        "# Title",
        ("[fine](docs/guide.md#a-heading) [top](#title) [line](docs/guide.md?plain=1#L5) "
         f"{repository}#title {repository}/actions/runs/1#summary"),
        "[missing](docs/missing.md)",
        "[wrong case](docs/Guide.md)",
        "[no such heading](docs/guide.md#no-such-heading)",
        "[no such heading here](#nowhere)",
        "[ignored](build.log)",
        "[outside](../elsewhere.md)",
        f"{repository}/blob/main/docs/absent.md",
        "[past the end](docs/guide.md?plain=1#L99)",
        f"[a workflow that is not there]({repository}/actions/workflows/absent.yml)",
        f"{repository}#nowhere-in-the-readme",
        TICK * 3 + "text",
        "[in a fence](docs/missing-too.md)",
        TICK * 3,
        TICK + "[in code](docs/missing-as-well.md)" + TICK,
        "[^1]: a footnote, not a link",
    ]) + "\n", encoding="utf-8")
    published = frozenset({"README.md", "docs", "docs/guide.md"})

    problems = link_problems(tmp_path, [readme], published=published)

    assert [problem.split(" -> ")[0] for problem in problems] == [
        f"README.md:{line}" for line in range(3, 13)], "\n".join(problems)
