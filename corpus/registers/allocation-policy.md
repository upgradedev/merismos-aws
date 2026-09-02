# Allocation policy

Agreed by the five member organisations, March 2026. This is the document the
fleet is obliged to apply, and the one a member points at when they think a
share was wrong.

## The ceiling

No single organisation receives more than **40%** of one offer. The point is not
fairness in the abstract. It is that an organisation which takes a whole pallet
and then cannot move it has wasted the whole pallet, and the donor stops calling.

## The rota

An organisation that received a share of the **last two offers in the same
category** goes to the back of the queue for the third. Categories are `ambient`,
`chilled`, `frozen`, `produce` and `non-food`.

This is the rule that most often produces an outcome a member dislikes, so the
published record always names which organisations were skipped and why. A
decision nobody can see is a decision that gets re-litigated by phone.

## Capacity is a veto, not a preference

A share is never allocated to an organisation that cannot store it. Cold storage
capacity is in `orgs/<id>.json` as `cold_storage_litres`, and an organisation
with `0` may not receive anything in the `chilled` or `frozen` categories at all.

Transport is the same. `has_van: false` means the share has to be within what a
volunteer carries on foot or by bus, which the register records as
`walk_in_limit_kg`.

## Premises constraints override everything, including the rota

Some members cannot accept some goods at all, for reasons that are about the
people they serve rather than about storage. These are recorded per organisation
as `premises_constraints` and they are absolute: an organisation with
`alcohol_free_premises` may not receive alcohol in any quantity, as part of any
mixed lot, including inside a gift hamper or a seasonal box.

**This is the rule that is hardest to apply from an offer title.** A donor
describing a pallet as "assorted ambient grocery" is describing it honestly and
has no idea which of our members runs a recovery programme or a school. Whoever
allocates the pallet has to open the manifest and then open the register. That
is the work this network was doing by hand and getting wrong.

## What the published record must and must not carry

It carries organisation names, categories, quantities, the reason for each
share, and the organisations skipped with the rule that skipped them.

It never carries a person. No name of anyone who collected, cooked, drove or
received; no address; no phone number; no national identifier. The record is
published to a public address and cannot be recalled. See `registers/retention.md`.
