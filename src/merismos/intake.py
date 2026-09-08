"""Taking an offer from a person rather than from a fixture.

A persona review's customer finding: a network could watch Merismos decide about
somebody else's offers and could not put in its own, because the corpus was a
fixture in a bucket. That is the gap between a demonstration and something a
network could use on Monday.

**Everything a person types is untrusted, and this is the one place untrusted
text enters the system by design.** The offer's note is read by an agent, and
prompt injection in it is not hypothetical: the gate already refuses a draft
whose offer text carries instructions aimed at the fleet. Refusing at intake as
well is not belt and braces, it is cheaper: a coordinator who typed something
that will be refused later should be told now, while they still remember what
they meant.

What this deliberately does **not** do is sanitise. It refuses and says why. A
field that quietly rewrites what somebody typed is a field they cannot trust,
and the thing being rewritten here is the description of food that people will
eat.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import date
from typing import Any

from .gate import _BYPASS, _EMAIL, _INJECTION, _NATIONAL_ID, _PHONE, _STREET

MAX_TITLE = 120
MAX_DONOR = 120
MAX_NOTE = 600
MAX_QUANTITY = 100_000

UNITS = ("kg", "units")
CATEGORIES = ("ambient", "chilled", "frozen", "produce", "non-food")


class Rejected(ValueError):
    """What a person typed cannot become an offer, and why, in their words."""


def _clean(value: Any, limit: int) -> str:
    """Trim, collapse whitespace, and drop control characters.

    Control characters are removed rather than refused, because nobody types
    one on purpose: they arrive from a paste out of a PDF or a phone keyboard.
    Everything a person can see and meant to type survives.
    """
    text = unicodedata.normalize("NFC", str(value or ""))
    text = "".join(c for c in text if unicodedata.category(c)[0] != "C" or c in "\n\t")
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text[:limit]


def offer_from_form(form: Mapping[str, Any], offer_id: str) -> dict[str, Any]:
    """Turn what somebody typed into an offer, or refuse and say why."""
    title = _clean(form.get("title"), MAX_TITLE)
    donor = _clean(form.get("donor"), MAX_DONOR)
    note = _clean(form.get("note"), MAX_NOTE)
    unit = _clean(form.get("unit"), 16).lower() or "kg"
    category = _clean(form.get("category"), 16).lower() or "ambient"

    if not title:
        raise Rejected("An offer needs a description. What is it?")
    if not donor:
        raise Rejected("An offer needs a donor. Who is giving it?")
    if unit not in UNITS:
        raise Rejected(f"{unit!r} is not a unit this network uses. Use kg or units.")
    if category not in CATEGORIES:
        raise Rejected(f"{category!r} is not one of {', '.join(CATEGORIES)}.")

    try:
        quantity = float(str(form.get("quantity", "")).strip())
    except ValueError:
        raise Rejected("How much? A number, in whichever unit you chose.") from None
    if not 0 < quantity <= MAX_QUANTITY:
        raise Rejected(f"A quantity has to be above zero and below {MAX_QUANTITY:,}.")

    collection_date = _a_date(form.get("collection_date"))
    use_by = _a_use_by(form.get("use_by"), collection_date)
    hours = _hours_out_of_the_fridge(form.get("hours_unrefrigerated"), category)
    allergens = _allergens(form.get("allergens"), form.get("allergens_unknown"))

    _refuse_a_person(title, donor, note)
    _refuse_an_instruction(f"{title}\n{note}")

    return {
        "id": offer_id,
        "title": title,
        "donor": donor,
        "category": category,
        "quantity": round(quantity, 2),
        "unit": unit,
        "collection_date": collection_date,
        "use_by": use_by,
        "note": note,
        "allergens": allergens,
        "hours_unrefrigerated": hours,
        "added_by": "the coordinator on duty",
    }


def _a_use_by(value, collection_date: str) -> str:
    """When it stops being safe to give away. Asked for, never inferred.

    **This field did not exist until 2026-09-08 and its absence was expensive.**
    The register's same-day rule turns on the gap between collection and use by,
    and a typed offer carried no use by at all, so a coordinator could not
    express the one condition that produced this network's worst published
    record. Every offer a person filed was silently a long dated one.

    Empty is allowed and is not a default. It means the donor did not say, the
    offer records that they did not say, and the fleet turns an unestablished
    shelf life into a finding rather than into a long one.
    """
    text = _clean(value, 32)
    if not text:
        return ""
    stamped = _a_date(text)
    if collection_date and stamped and stamped < collection_date:
        raise Rejected(
            f"The use by date {stamped} is before the collection date "
            f"{collection_date}. One of the two is wrong, and guessing which one "
            f"is not something to do on somebody else's behalf."
        )
    return stamped


def _allergens(declared, unknown) -> list[str] | None:
    """What is in it, or ``None`` for nobody has established what is in it.

    The distinction is the whole point and it used to be flattened to ``[]``,
    which means "checked, and there are none".

    ``None`` is not a safe default. It is an unsafe one, recorded honestly, and
    the specialists are what turn it into a finding.
    """
    if str(unknown).strip().lower() in ("1", "true", "on", "yes"):
        return None
    text = _clean(declared, 200)
    if not text:
        return None
    found = [part.strip().lower() for part in text.replace(";", ",").split(",")]
    return sorted({item for item in found if item}) or None


def _a_date(value: Any) -> str:
    """A collection date, in the one format every other offer in the filing uses.

    Asked for rather than defaulted to today. The food safety specialist compares
    it against a use-by date, and a date this code invented would be evidence in
    a published record that no person put there.
    """
    text = _clean(value, 10)
    if not text:
        raise Rejected("When is it being collected? A date, like 2026-09-14.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise Rejected(f"{text!r} is not a date this network writes. Use 2026-09-14.")
    try:
        date.fromisoformat(text)
    except ValueError:
        raise Rejected(f"There is no such day as {text}.") from None
    return text


def _hours_out_of_the_fridge(value: Any, category: str) -> float | None:
    """How long a chilled or frozen offer has been warm, which decides everything.

    ``food_safety`` refuses a chilled offer outright when this is missing, and it
    is right to: absent evidence is a finding, never a pass. So the form has to
    ask, and a coordinator has to be told **here** rather than after a run that
    takes minutes and ends in a refusal they could not have avoided.

    An ambient offer keeps ``None`` rather than a helpful zero. Zero would be a
    measurement nobody took, about a question nobody asked.
    """
    text = _clean(value, 8)
    if category not in ("chilled", "frozen"):
        return None
    if not text:
        raise Rejected(
            "A chilled or frozen offer has to say how many hours it has been out "
            "of the fridge. The fleet refuses one that does not, because absent "
            "evidence about a cold chain is a finding rather than a pass."
        )
    try:
        hours = float(text)
    except ValueError:
        raise Rejected(f"{text!r} is not a number of hours.") from None
    if not 0 <= hours <= 168:
        raise Rejected("Hours out of the fridge has to be between 0 and 168.")
    return round(hours, 1)


def _refuse_a_person(*fields: str) -> None:
    """Nothing about a person may enter, because the record is published.

    Refused at the door rather than at the gate. Both refuse it; only one of
    them refuses it while the person still has the message in front of them.

    Each field is checked **on its own**. Joining them first would let the
    trailing digits of one run into the leading digits of the next and match the
    phone pattern, because that pattern allows a space between digits and a
    newline is a space. Refusing a bakery called "Fournos 24" because the
    quantity beside it was 240 would be a refusal nobody could act on.
    """
    for text in fields:
        _refuse_a_person_in(text)


def _refuse_a_person_in(text: str) -> None:
    for pattern, what in (
        (_EMAIL, "an email address"),
        (_PHONE, "what reads as a phone number"),
        (_STREET, "a street address"),
        (_NATIONAL_ID, "a national identifier"),
    ):
        if pattern.search(text):
            raise Rejected(
                f"That contains {what}. A published record never carries a person, so "
                f"this would be refused later anyway. Describe the food, not the people."
            )


def _refuse_an_instruction(text: str) -> None:
    """Text aimed at the fleet rather than describing the goods."""
    if _INJECTION.search(text) or _BYPASS.search(text):
        raise Rejected(
            "That reads as an instruction to the system rather than a description of "
            "the food. An offer says what is in the crate; it does not tell the fleet "
            "what to decide."
        )


def next_offer_id(existing: list[Mapping[str, Any]]) -> str:
    """The next id in this network's own sequence.

    Sequential rather than random, because a coordinator reads these aloud on
    the phone and `offer-4484` is sayable in a way a uuid is not.
    """
    numbers = []
    for offer in existing:
        match = re.fullmatch(r"offer-(\d+)", str(offer.get("id", "")))
        if match:
            numbers.append(int(match.group(1)))
    return f"offer-{(max(numbers) + 1) if numbers else 1}"


def as_document(offer: Mapping[str, Any]) -> str:
    """The offer as it is stored, pretty printed because a person may read it."""
    return json.dumps(dict(offer), indent=2, sort_keys=True)
