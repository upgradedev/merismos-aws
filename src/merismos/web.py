"""The screens a coordinator actually uses.

Server rendered, from the same Lambda that runs the fleet. No build step, no
bundle, no CDN and no external request of any kind: a page that needs a font
from somewhere else is a page that breaks when that somewhere else is down, and
this one has to still be standing on 2026-10-08 for a judge who is not us.

**Four screens, and the third is the product.**

``/`` the offers waiting on somebody. This is the group chat, replaced.
``/offer/<id>`` what the fleet decided and why, including who was skipped.
``/approve/<id>`` **the card.** The one moment a person is in the loop. It shows
the exact bytes, the digest of those bytes, what the second model said, and what
this approval does not authorise.
``/record/<id>`` the published record, which is what a funder opens in March.

The design rule throughout: **show the reasoning, not just the answer.** A
coordinator who cannot see why the shelter was skipped will phone the shelter,
and then the fleet has cost them time rather than saved it.
"""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from typing import Any

# --------------------------------------------------------------------------
# One stylesheet, inlined. System fonts only.
# --------------------------------------------------------------------------

STYLE = """
:root{
  --ink:#14171a; --dim:#5b6570; --line:#e3e7eb; --bg:#fbfcfd; --card:#fff;
  --ok:#0f7b4f; --ok-bg:#e8f6ef; --warn:#8a5a00; --warn-bg:#fdf3e0;
  --stop:#a3201c; --stop-bg:#fceceb; --accent:#1a4fa0; --accent-bg:#eaf0fb;
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --ink:#e8ecef; --dim:#9aa5b1; --line:#2b3239; --bg:#0f1316; --card:#161b20;
  --ok:#5fd39b; --ok-bg:#123024; --warn:#e8b45f; --warn-bg:#33280f;
  --stop:#f08b86; --stop-bg:#3a1817; --accent:#7fa9f0; --accent-bg:#152238;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-text-size-adjust:100%}
.wrap{max-width:60rem;margin:0 auto;padding:1.25rem}
header.top{border-bottom:1px solid var(--line);background:var(--card)}
header.top .wrap{display:flex;gap:1rem;align-items:baseline;flex-wrap:wrap;padding:.9rem 1.25rem}
.brand{font-weight:700;letter-spacing:-.01em;text-decoration:none;color:var(--ink);font-size:1.05rem}
.brand span{color:var(--dim);font-weight:400}
nav a{color:var(--dim);text-decoration:none;margin-right:1rem;font-size:.9rem}
nav a:hover,a:focus-visible{color:var(--accent);text-decoration:underline}
h1{font-size:1.5rem;line-height:1.25;margin:.2rem 0 .4rem;letter-spacing:-.02em}
h2{font-size:1.05rem;margin:1.8rem 0 .6rem;letter-spacing:-.01em}
p.lede{color:var(--dim);margin:.2rem 0 1.2rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:1.1rem;margin:.8rem 0}
.card h3{margin:0 0 .3rem;font-size:1.05rem}
.row{display:flex;gap:1rem;justify-content:space-between;align-items:flex-start;flex-wrap:wrap}
.tag{display:inline-block;font-size:.75rem;font-weight:600;padding:.2rem .55rem;border-radius:999px;
  border:1px solid transparent;white-space:nowrap}
.t-ok{background:var(--ok-bg);color:var(--ok)}
.t-warn{background:var(--warn-bg);color:var(--warn)}
.t-stop{background:var(--stop-bg);color:var(--stop)}
.t-info{background:var(--accent-bg);color:var(--accent)}
table{width:100%;border-collapse:collapse;margin:.5rem 0;font-size:.95rem}
th,td{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:.78rem;text-transform:uppercase;letter-spacing:.04em;color:var(--dim);font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.btn{display:inline-block;background:var(--accent);color:#fff;border:0;border-radius:8px;
  padding:.7rem 1.1rem;font:inherit;font-weight:600;cursor:pointer;text-decoration:none}
.btn:hover{filter:brightness(1.08)}
.btn.secondary{background:transparent;color:var(--accent);border:1px solid var(--line)}
.btn[disabled]{opacity:.55;cursor:not-allowed}
.why{color:var(--dim);font-size:.88rem;margin:.35rem 0 0}
pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:.9rem;
  overflow-x:auto;font-size:.82rem;line-height:1.5;margin:.5rem 0;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.88em}
.digest{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.78rem;word-break:break-all;color:var(--dim)}
.note{border-left:3px solid var(--accent);background:var(--accent-bg);padding:.7rem .9rem;
  border-radius:0 8px 8px 0;margin:.8rem 0;font-size:.92rem}
.note.amber{border-left-color:var(--warn);background:var(--warn-bg)}
.note.stop{border-left-color:var(--stop);background:var(--stop-bg)}
ul.reasons{margin:.4rem 0 0;padding-left:1.1rem}
ul.reasons li{margin:.3rem 0;font-size:.92rem}
footer{color:var(--dim);font-size:.82rem;border-top:1px solid var(--line);margin-top:2.5rem;padding:1.2rem 0}
.skip{position:absolute;left:-9999px}
.skip:focus{left:.5rem;top:.5rem;background:var(--card);padding:.5rem;border-radius:6px;z-index:9}
@media(max-width:480px){.wrap{padding:1rem}h1{font-size:1.28rem}}
"""


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _readable(slug: str) -> str:
    """A network name a coordinator would recognise, not the key it is stored under.

    A UX review caught the raw `kypseli-network` printed on the first line of
    the site. Nobody calls their network that; it is an identifier that leaked
    into a sentence.
    """
    words = str(slug).replace("_", "-").split("-")
    if words and words[-1].lower() == "network":
        words = words[:-1]
    return " ".join(w.capitalize() for w in words if w) + " mutual aid network"


def page(title: str, body: str, subtitle: str = "", refresh_seconds: int = 0) -> str:
    """One shell for every screen.

    ``refresh_seconds`` is how a long run is polled. A meta refresh rather than
    a script, because every screen here loads no JavaScript and that is asserted
    per screen.
    """
    refresh = (
        f'<meta http-equiv="refresh" content="{refresh_seconds}">' if refresh_seconds else ""
    )
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{refresh}
<title>{_e(title)} · Merismos</title>
<meta name="description" content="{_e(subtitle or 'Apportionment of donated food, and the record of how it was decided.')}">
<style>{STYLE}</style>
</head><body>
<a class="skip" href="#main">Skip to content</a>
<header class="top"><div class="wrap">
  <a class="brand" href="/">Merismos <span>&nbsp;apportionment, and the record</span></a>
  <nav>
    <a href="/">Offers</a><a href="/records">Published</a><a href="/how">How it decides</a>
  </nav>
</div></header>
<main id="main" class="wrap">{body}</main>
<footer><div class="wrap">
  Every organisation and person here is invented. Merismos publishes organisations and quantities,
  and never a person.
</div></footer>
</body></html>"""


# --------------------------------------------------------------------------
# Screens
# --------------------------------------------------------------------------

_OUTCOME = {
    "awaiting_approval": ("t-warn", "waiting on you"),
    "approved": ("t-ok", "approved"),
    "blocked": ("t-stop", "refused"),
    "refused_by_gate": ("t-stop", "refused by the gate"),
    "nothing_to_allocate": ("t-info", "nothing to allocate"),
    "published": ("t-ok", "published"),
}


def inbox(offers: Sequence[Mapping[str, Any]], network: str) -> str:
    """What is waiting on somebody. This screen replaces the group chat."""
    if not offers:
        body = '<div class="card"><h3>Nothing waiting</h3><p class="why">No offers in the '
        body += "network's filing right now.</p>"
        body += '<p style="margin:.9rem 0 0"><a class="btn" href="/offers/new">Add one</a></p></div>'
        return page("Offers", body)

    cards = []
    for offer in offers:
        oid = _e(offer.get("id"))
        cards.append(f"""
<div class="card">
  <div class="row">
    <div>
      <h3>{_e(offer.get('title'))}</h3>
      <p class="why">{_e(offer.get('donor'))} &middot; {_e(offer.get('quantity'))}
        {_e(offer.get('unit'))} &middot; {_e(offer.get('category'))} &middot;
        collect by {_e(offer.get('collection_date'))}</p>
    </div>
    <span class="tag t-info">{oid}</span>
  </div>
  <p class="why">{_e(offer.get('note', ''))}</p>
  <p style="margin:.9rem 0 0"><a class="btn" href="/offer/{oid}">Work out the split</a></p>
</div>""")

    body = f"""
<h1>Offers waiting on somebody</h1>
<p class="lede">{_e(_readable(network))}. Five organisations share whatever gets donated. Merismos
does the apportionment and brings back one thing to approve.</p>
<p style="margin:0 0 1.2rem"><a class="btn secondary" href="/offers/new">Add an offer</a></p>
{''.join(cards)}
<div class="note">Nothing here publishes on its own. Every offer stops at a card a person reads,
and the publish is the last step.</div>"""
    return page("Offers", body, "Offers waiting on a decision")


def decision(result: Any, offer: Mapping[str, Any], network: str) -> str:
    """What the fleet decided, and every reason behind it."""
    cls, label = _OUTCOME.get(result.outcome, ("t-info", result.outcome))
    oid = _e(offer.get("id"))
    unit = _e(offer.get("unit", ""))

    head = f"""
<h1>{_e(offer.get('title'))}</h1>
<p class="lede">{_e(offer.get('donor'))} &middot; {_e(offer.get('quantity'))} {unit}
  &middot; <span class="tag {cls}">{_e(label)}</span></p>"""

    if result.outcome in ("blocked", "refused_by_gate"):
        body = head + f"""
<div class="note stop"><strong>Refused, and here is why.</strong><br>{_e(result.note)}</div>
{_specialists(result)}
<p><a class="btn secondary" href="/">Back to offers</a></p>"""
        return page(offer.get("title", "Offer"), body)

    if result.draft is None:
        body = head + f'<div class="note">{_e(result.note)}</div><p><a class="btn secondary" href="/">Back</a></p>'
        return page(offer.get("title", "Offer"), body)

    shares = "".join(
        f"<tr><td>{_e(a['org'])}</td><td class='num'>{_e(a['quantity'])} {unit}</td>"
        f"<td class='num'>{_e(a.get('share_of_offer',''))}</td><td>{_e(a['reason'])}</td></tr>"
        for a in result.draft.allocations
    )
    skipped = _skipped(result)

    body = head + f"""
<h2>The split</h2>
<div class="scroll"><table>
  <thead><tr><th>Organisation</th><th class="num">Share</th><th class="num">Of offer</th><th>Why</th></tr></thead>
  <tbody>{shares}</tbody>
</table></div>
{skipped}
{_specialists(result)}
<h2>What happens next</h2>
<div class="note amber"><strong>Nothing is published yet.</strong> Merismos has done the work and
stopped. A person reads the exact bytes and approves them, and only then does anything leave this
screen.</div>
<p><a class="btn" href="/approve/{oid}{_run_query(result)}">Read it and decide</a>
   <a class="btn secondary" href="/">Back to offers</a></p>"""
    return page(offer.get("title", "Offer"), body, "What the fleet decided and why")


def _skipped(result: Any) -> str:
    barred = sorted(result.draft.must_not_receive) if result.draft else []
    if not barred:
        return ""
    reasons = []
    for name in barred:
        why = next(
            (
                f.detail
                for e in result.envelopes
                for f in e.findings
                if name in f.detail
            ),
            "excluded by the network's policy",
        )
        reasons.append(f"<li><strong>{_e(name)}</strong>: {_e(why)}</li>")
    return f"""
<h2>Not receiving a share, and the rule that decided it</h2>
<p class="why">A decision nobody can see is a decision that gets re-litigated by phone.</p>
<ul class="reasons">{''.join(reasons)}</ul>"""


def _specialists(result: Any) -> str:
    if not result.envelopes:
        return ""
    rows = []
    for e in result.envelopes:
        cls = {"ok": "t-ok", "needs_changes": "t-warn", "blocked": "t-stop", "error": "t-stop"}.get(
            e.status.value, "t-info"
        )
        findings = "".join(
            f"<li>{_e(f.detail)}</li>" for f in e.findings
        )
        rows.append(f"""
<div class="card">
  <div class="row"><h3>{_e(e.specialist)}</h3>
    <span class="tag {cls}">{_e(e.status.value.replace('_',' '))}</span></div>
  {f'<p class="why">{_e(e.reason)}</p>' if e.reason else ''}
  {f'<ul class="reasons">{findings}</ul>' if findings else ''}
</div>""")
    opened = result.read_log.get("reads", []) if result.read_log else []
    served = [r["path"] for r in opened if r.get("served")]
    read_note = (
        f'<p class="why">The specialists opened {len(served)} '
        f'{"file" if len(served) == 1 else "files"} from the network\'s own filing: '
        f'<code>{_e(", ".join(served[:6]))}</code>'
        f'{" and more" if len(served) > 6 else ""}.</p>'
        if served else ""
    )
    return f"<h2>How it was decided</h2>{read_note}{''.join(rows)}"


def approval_card(
    result: Any, offer: Mapping[str, Any], network: str, key: str
) -> str:
    """The one moment a person is in the loop. This is the hero screen.

    The run id travels with the form. It is what ties these bytes back to the
    decision the person actually read: without it the approve route would decide
    again, and a second run with a model in it can reach a different answer than
    the one on the screen behind this page.
    """
    body_bytes = result.draft.body
    from .approval import digest as _digest

    sha = _digest(network, key, body_bytes)
    advisories = list(result.verdict.advisories) if result.verdict else []
    critic = result.verdict.critic_model if result.verdict else ""

    critic_panel = ""
    if advisories:
        items = "".join(f"<li>{_e(a)}</li>" for a in advisories)
        critic_panel = f"""
<div class="note amber">
  <strong>A second model, from a different family, reviewed this.</strong>
  {f'<span class="digest">{_e(critic)}</span>' if critic else ''}
  <ul class="reasons">{items}</ul>
  <p class="why" style="margin-top:.5rem">It cannot approve, cannot remove a finding and cannot
  change the result above. It only adds what you are reading now.</p>
</div>"""

    body = f"""
<h1>Approve this record</h1>
<p class="lede">You are approving <strong>these exact bytes</strong>. Change one character
afterwards and the writer refuses it.</p>

{critic_panel}

<h2>What will be published</h2>
<pre>{_e(body_bytes)}</pre>

<h2>What you are signing</h2>
<div class="scroll"><table>
 <tr><th>Network</th><td>{_e(network)}</td></tr>
 <tr><th>Address</th><td><code>{_e(key)}</code>, readable by anyone with no account</td></tr>
 <tr><th>Digest</th><td class="digest">{_e(sha)}</td></tr>
 <tr><th>Valid for</th><td>15 minutes, then it must be read and approved again</td></tr>
 <tr><th>Uses</th><td>One. The nonce is spent by a conditional write, so it cannot be replayed</td></tr>
</table></div>

<div class="note"><strong>What this approval does not authorise.</strong> It covers this one
address and these one set of bytes. It does not let the fleet publish anything else, edit the
network's filing, or publish again without you.</div>

<form method="post" action="/approve/{_e(offer.get('id'))}">
  <input type="hidden" name="run" value="{_e(getattr(result, 'run_id', ''))}">
  <p><label>Your name, for the record<br>
    <input name="approved_by" required placeholder="the coordinator on duty"
      style="font:inherit;padding:.6rem;border:1px solid var(--line);border-radius:8px;
             background:var(--card);color:var(--ink);width:min(100%,22rem);margin-top:.3rem"></label></p>
  <p><button class="btn" type="submit">I have read these bytes. Publish them.</button>
     <a class="btn secondary" href="/offer/{_e(offer.get('id'))}">Not yet</a></p>
</form>"""
    return page("Approve", body, "The one moment a person is in the loop")


def published(receipt: Mapping[str, Any], body_text: str) -> str:
    """What a funder opens in March."""
    body = f"""
<h1>Published</h1>
<div class="note"><strong>This record is public.</strong> Anyone can read it with no account, which
is the point: the answer to "what happened to the Tuesday pallet" should not require asking.</div>
<h2>The record</h2>
<pre>{_e(body_text)}</pre>
<h2>The receipt</h2>
<div class="scroll"><table>
 <tr><th>Approved by</th><td>{_e(receipt.get('approved_by'))}</td></tr>
 <tr><th>Address</th><td><code>{_e(receipt.get('key'))}</code></td></tr>
 <tr><th>Digest</th><td class="digest">{_e(receipt.get('content_digest'))}</td></tr>
 <tr><th>Run</th><td><code>{_e(receipt.get('run_id'))}</code></td></tr>
</table></div>
<p><a class="btn secondary" href="/">Back to offers</a></p>"""
    return page("Published", body, "A published allocation record")


def how_it_decides(catalogue_doc: Mapping[str, Any], config_doc: Mapping[str, Any]) -> str:
    """The page that answers "why should I trust this" without a sales pitch."""
    specialists = "".join(
        f"<tr><td><strong>{_e(name)}</strong></td><td>{_e(spec['why'])}</td>"
        f"<td class='why'>{_e(', '.join(spec['reads']))}</td></tr>"
        for name, spec in catalogue_doc.get("specialists", {}).items()
    )
    return page(
        "How it decides",
        f"""
<h1>How it decides, and what it cannot do</h1>
<p class="lede">Everything on this page is enforced in code rather than asked for in a prompt.</p>

<h2>The specialists</h2>
<div class="scroll"><table>
 <thead><tr><th>Who wakes</th><th>Why they exist</th><th>What they may read</th></tr></thead>
 <tbody>{specialists}</tbody></table></div>

<h2>What the agents are not allowed to do</h2>
<div class="scroll"><table>
 <tr><th>Bound</th><td>Reads are limited to
   <code>{_e(', '.join(config_doc.get('read_scope', [])))}</code></td></tr>
 <tr><th>Budget</th><td>{_e(config_doc.get('read_budget_per_specialist'))} files per specialist,
   per offer. A refused read costs nothing, so a bad guess is not punished</td></tr>
 <tr><th>Publishing</th><td>No agent can publish. The identity that reads cannot write, and AWS
   refuses it rather than our code doing so</td></tr>
 <tr><th>The gate</th><td>Deterministic. A model cannot argue its way past it, and the second
   model can only add to what you read</td></tr>
</table></div>

<div class="note"><strong>The record never contains a person.</strong> No name, address, phone
number or national identifier reaches a published record. The gate refuses a draft carrying one and
an approver cannot override that.</div>
""",
        "What the fleet may and may not do",
    )


def waiting(offer: Mapping[str, Any], run_id: str, state: Mapping[str, Any], model: str) -> str:
    """The fleet is reading. Say what it is doing, not that something is.

    Refreshed by a meta tag rather than a script. Every screen here loads no
    JavaScript, which is asserted per screen, and that guarantee is worth more
    than a smoother spinner.
    """
    answered = state.get("specialists_answered", 0)
    dots = "".join(
        f'<span class="tag {"t-ok" if i < answered else "t-info"}">{name}</span> '
        for i, name in enumerate(["food-safety", "capacity", "equity", "premises"])
    )
    body = f"""
<h1>The fleet is reading</h1>
<p class="lede">{_e(offer.get('title'))} &middot; {_e(offer.get('quantity'))} {_e(offer.get('unit'))}</p>

<div class="card">
  <div class="row"><h3>{_e(state.get('stage', 'starting'))}</h3>
    <span class="tag t-warn">{_e(answered)} of 4 answered</span></div>
  <p style="margin:.8rem 0 .3rem">{dots}</p>
  <p class="why">Each specialist opens the network's own filing and decides what to read.
  {_e(model)} takes about a minute and a half per specialist, so this page waits.</p>
</div>

<div class="note"><strong>Why this takes minutes rather than seconds.</strong> The specialists are
not matching patterns. Each one is handed the filing and a question and chooses which files to
open, and the files it chose are recorded. That is the difference this product is arguing for, and
it is not free.</div>

<p class="why">This page refreshes itself. Nothing here runs a script.</p>
<p><a class="btn secondary" href="/">Back to offers</a></p>"""
    return page(
        "Reading",
        body,
        "The fleet is reading the network's filing",
        refresh_seconds=4,
    )


def ready(offer: Mapping[str, Any], network: str, model: str) -> str:
    """The offer, before anybody has asked the fleet to look at it."""
    using = (
        f"<strong>{_e(model)}</strong> reads the filing"
        if model and model.lower() not in ("none", "off", "stub")
        else "the deterministic rules run, with no model configured"
    )
    body = f"""
<h1>{_e(offer.get('title'))}</h1>
<p class="lede">{_e(offer.get('donor'))} &middot; {_e(offer.get('quantity'))}
  {_e(offer.get('unit'))} &middot; {_e(offer.get('category'))} &middot;
  collect by {_e(offer.get('collection_date'))}</p>

<div class="card">
  <h3>What the donor said</h3>
  <p class="why">{_e(offer.get('note', ''))}</p>
</div>

<div class="note"><strong>What happens when you press this.</strong> Four specialists wake. Each is
handed the network's filing and a question, not an answer, and each decides which files to open.
Here {using}. Nothing is published: the run stops at a card you read.</div>

<form method="post" action="/offer/{_e(offer.get('id'))}">
  <p><button class="btn" type="submit">Ask the fleet</button>
     <a class="btn secondary" href="/">Back to offers</a></p>
</form>"""
    return page(offer.get("title", "Offer"), body, "An offer waiting on a decision")


def _run_query(result: Any) -> str:
    """The run id as a query string, or nothing at all.

    Nothing at all is the case where a chore ran inside the request, which the
    CLI and the offline tests still do. The approve route falls back to deciding
    when it is given no run, so an absent id degrades to the old behaviour rather
    than to a broken link.
    """
    run_id = str(getattr(result, "run_id", "") or "")
    return f"?run={run_id}" if run_id else ""


def recorded(record: Mapping[str, Any]) -> Any:
    """A finished chore rebuilt from the thread, for a caller outside this module.

    The handler needs the same object the decision screen renders, so that the
    card, the digest and the publish all come from the run the person read.
    """
    return _Recorded(record)


def decision_from_record(record: Mapping[str, Any], offer: Mapping[str, Any], network: str) -> str:
    """Render a finished chore that was recorded in the thread.

    The live screens read the provenance thread rather than a second store,
    because the thread was always the memory and the audit trail. A run that
    finished four minutes ago renders from exactly what a judge can also read.
    """
    return decision(_Recorded(record), offer, network)


class _Recorded:
    """A finished chore, rebuilt from what the thread recorded.

    Only the fields the decision screen reads. Deliberately not the real
    dataclasses: rebuilding an Envelope would mean re-validating a refusal that
    was already validated when it was written, and a validation error while
    rendering history would hide the history.
    """

    def __init__(self, record: Mapping[str, Any]) -> None:
        self.outcome = record.get("outcome", "")
        self.note = record.get("note", "")
        self.run_id = record.get("run_id", "")
        self.read_log = record.get("reads", {}) or {}
        self.envelopes = [_RecordedEnvelope(e) for e in record.get("envelopes", [])]
        draft = record.get("draft_allocations")
        self.draft = (
            _RecordedDraft(record) if record.get("outcome") in ("awaiting_approval", "approved")
            or draft else None
        )
        self.verdict = _RecordedVerdict(record.get("verdict") or {})


class _RecordedEnvelope:
    def __init__(self, e: Mapping[str, Any]) -> None:
        self.specialist = e.get("specialist", "")
        self.reason = e.get("reason", "")
        self.meta = e.get("meta", {}) or {}
        self.status = _Status(e.get("status", ""))
        self.findings = [_RecordedFinding(f) for f in e.get("findings", [])]


class _RecordedFinding:
    def __init__(self, f: Mapping[str, Any]) -> None:
        self.check = f.get("check", "")
        self.severity = f.get("severity", "")
        self.detail = f.get("detail", "")
        self.evidence = f.get("evidence", "")


class _Status:
    def __init__(self, value: str) -> None:
        self.value = value


class _RecordedVerdict:
    def __init__(self, v: Mapping[str, Any]) -> None:
        self.passed = v.get("passed", False)
        self.advisories = v.get("advisories", []) or []
        self.critic_model = v.get("critic_model", "")


class _RecordedDraft:
    def __init__(self, record: Mapping[str, Any]) -> None:
        self.body = record.get("draft_body", "")
        self.allocations = record.get("draft_allocations", []) or []
        self.must_not_receive = set(record.get("draft_must_not_receive", []) or [])


def custody_chain(offer: Mapping[str, Any], chain: Mapping[str, Any]) -> str:
    """The custody chain for one offer, and whether it still verifies.

    This is what "follow the thread back" means when somebody wants more than a
    list. Each stage carries the hash of the stage before it, so altering an
    earlier one changes every hash after it and the chain stops verifying.

    Stated plainly on the page, because the distinction is the honest part: the
    ledger is append only **by interface**, a property of the code rather than
    of the storage. The chain is what makes an edit made from outside that code
    detectable. It does not make the row immutable.
    """
    if not chain.get("nodes"):
        body = f"""
<h1>No custody chain yet</h1>
<div class="note">Nothing has been decided for {_e(offer.get('id'))}, so there is no chain to
verify. A chain appears once the fleet has run.</div>
<p><a class="btn secondary" href="/offer/{_e(offer.get('id'))}">Ask the fleet</a></p>"""
        return page("Custody chain", body)

    verified = chain.get("verified")
    rows = "".join(
        f"<tr><td>{i + 1}</td><td>{_e(n.get('stage'))}</td><td>{_e(n.get('actor'))}</td>"
        f"<td class='digest'>{_e(str(n.get('node_hash', ''))[:16])}</td>"
        f"<td class='digest'>{_e(str(n.get('parent_hash', ''))[:16])}</td></tr>"
        for i, n in enumerate(chain["nodes"])
    )
    verdict = (
        f'<div class="note"><strong>Verified.</strong> {_e(chain.get("detail"))}</div>'
        if verified
        else f'<div class="note stop"><strong>This chain does not verify.</strong> '
        f'{_e(chain.get("detail"))}</div>'
    )

    body = f"""
<h1>Custody chain</h1>
<p class="lede">{_e(offer.get('title'))} &middot; {_e(chain.get('stages'))} stages</p>
{verdict}
<div class="scroll"><table>
 <thead><tr><th>#</th><th>Stage</th><th>Who</th><th>Hash</th><th>Follows</th></tr></thead>
 <tbody>{rows}</tbody>
</table></div>
<p class="why">Head: <span class="digest">{_e(chain.get('head_hash'))}</span></p>
<div class="note"><strong>What this does and does not prove.</strong> Each stage carries the hash of
the one before it, so changing an earlier stage changes every hash after it and this page stops
saying verified. The ledger underneath is append only by interface, which is a property of the code
rather than of the storage, and a chain makes an edit made from outside that code detectable rather
than impossible.</div>
<p><a class="btn secondary" href="/records">Published records</a></p>"""
    return page("Custody chain", body, "The verifiable custody chain for one offer")


def new_offer_form(error: str = "", values: Mapping[str, Any] | None = None) -> str:
    """A coordinator's own offer, in the fields they already have on the phone.

    The persona review's customer finding was that the corpus is a fixture: a
    network can watch Merismos decide about somebody else's offers and cannot
    put in its own. That is the gap between a demonstration and a thing a
    network could use on Monday, and it is one form wide.

    Deliberately short. A coordinator standing in a doorway with a phone will not
    fill in twenty fields, and every field here is one the donor's own message
    already contains.

    Two of them exist because of what the fleet does downstream rather than
    because a form wanted them. ``collection_date`` is compared against a use-by
    date by the food safety specialist, and ``hours_unrefrigerated`` is what that
    same specialist refuses a chilled offer for lacking. Asking here costs a
    coordinator five seconds; not asking costs them a run that takes minutes and
    ends in a refusal they had no way to avoid.
    """
    v = values or {}
    warn = f'<div class="note stop">{_e(error)}</div>' if error else ""
    return page(
        "Add an offer",
        f"""
<h1>Add an offer</h1>
<p class="lede">What the donor told you, and nothing the donor's own message does not already
contain. A coordinator standing in a doorway will not fill in twenty fields.</p>
{warn}
<form method="post" action="/offers/new">
  <div class="card">
    <p><label>What is it<br>
      <input name="title" required maxlength="120" value="{_e(v.get('title', ''))}"
        placeholder="End of day bread and vegetables" style="{_FIELD}"></label></p>
    <p><label>Who is giving it<br>
      <input name="donor" required maxlength="120" value="{_e(v.get('donor', ''))}"
        placeholder="Neighbourhood bakery" style="{_FIELD}"></label></p>
    <div class="row">
      <p><label>How much<br>
        <input name="quantity" required type="number" step="any" min="0.01"
          value="{_e(v.get('quantity', ''))}" placeholder="240" style="{_FIELD}"></label></p>
      <p><label>In what<br>
        <select name="unit" style="{_FIELD}">
          {_options(("kg", "kilograms"), ("units", "units"), chosen=v.get("unit", "kg"))}
        </select></label></p>
      <p><label>Kept how<br>
        <select name="category" style="{_FIELD}">
          {_options(*(((c, c)) for c in _CATEGORIES), chosen=v.get("category", "ambient"))}
        </select></label></p>
    </div>
    <div class="row">
      <p><label>Collected when<br>
        <input name="collection_date" required type="date" style="{_FIELD}"
          value="{_e(v.get('collection_date', ''))}"></label></p>
      <p><label>Hours out of the fridge<br>
        <input name="hours_unrefrigerated" type="number" step="any" min="0" max="168"
          value="{_e(v.get('hours_unrefrigerated', ''))}" placeholder="0" style="{_FIELD}">
        <span class="why">Chilled and frozen only. The fleet refuses one that does not
        say, because absent evidence about a cold chain is a finding and not a
        pass.</span></label></p>
    </div>
    <p><label>Anything the donor said<br>
      <textarea name="note" rows="3" maxlength="600" style="{_FIELD}"
        placeholder="Needs collecting before 19:00. Includes seasonal gift hampers."
        >{_e(v.get('note', ''))}</textarea></label></p>
  </div>

  <div class="note"><strong>What happens to what you type.</strong> It becomes an offer in this
  network's filing and the fleet reads it like any other. It is never sent anywhere else. Do not put
  a person's name or address in the note: the gate refuses a record carrying one, and it is easier
  not to type it.</div>

  <p><button class="btn" type="submit">Add it</button>
     <a class="btn secondary" href="/">Back to offers</a></p>
</form>""",
        "Add an offer to this network's filing",
    )


_FIELD = (
    "font:inherit;padding:.6rem;border:1px solid var(--line);border-radius:8px;"
    "background:var(--card);color:var(--ink);width:min(100%,22rem);margin-top:.3rem"
)


_CATEGORIES = ("ambient", "chilled", "frozen", "produce", "non-food")


def _options(*pairs: tuple[str, str], chosen: Any = "") -> str:
    """Options with the person's own choice still selected.

    A refusal that silently reset the dropdowns would be a refusal that made a
    coordinator retype what was never wrong with it.
    """
    out = []
    for value, label in pairs:
        mark = " selected" if str(chosen) == value else ""
        out.append(f'<option value="{_e(value)}"{mark}>{_e(label)}</option>')
    return "".join(out)
