# Food safety rules

These are deterministic. They are checked by arithmetic and by dates, never by
judgement, because the failure they prevent makes someone ill.

## Cold chain

A `chilled` offer that has been above 8 degrees for more than **four hours** is
refused in full. Not reduced, not allocated to whoever can collect fastest.
Refused, with the reason recorded.

`hours_unrefrigerated` on the offer is what this is measured against. An offer
in the `chilled` or `frozen` category that does not carry that field is also
refused, because absent evidence is a finding and never a pass.

## Use by

An item whose `use_by` is on or before the collection date is refused. An item
whose `use_by` is within 24 hours of collection may be allocated only to an
organisation with `same_day_service: true`.

## Allergens

`allergens` on the offer is a list. An organisation whose
`premises_constraints` name an allergen may not receive a lot containing it,
whatever the quantity and however it is packed.
