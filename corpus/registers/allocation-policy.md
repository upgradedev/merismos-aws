# Allocation policy

Agreed by the five member organisations, March 2026. This is the document the
fleet is obliged to apply, and the one a member points at when they think a
share was wrong.

## What happens to what nobody can take

An offer is not always fully allocable under these rules, and when it is not, the
quantity left over is published with the shares rather than left for a reader to
work out by subtraction. A coordinator seeing "124 kg still needs a home" can ring
a sixth organisation. A coordinator seeing three shares that do not add up assumes
the arithmetic is theirs to check.

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

## Storage is a veto. Transport is a cap. They are not the same rule

This section said "Transport is the same" and then described something different,
and on 2026-09-08 the two readings produced two different published records. It is
written out properly now, because a rule a member points at has to be the rule the
fleet applies.

**Cold storage is a veto on the organisation.** Capacity is in `orgs/<id>.json` as
`cold_storage_litres`, and an organisation with `0` may not receive anything in the
`chilled` or `frozen` categories at all. There is no share small enough to be safe
in a cupboard.

**Transport is a cap on the share, not a veto on the organisation.**
`has_van: false` does not mean the member is skipped. It means their share may not
exceed `walk_in_limit_kg`, which is what a volunteer carries on foot or by bus. A
shelter that can carry twenty kilos of bread should be given twenty kilos of bread.
Excluding it instead helps nobody and leaves food unallocated.

Where the offer is not counted in kilograms the cap cannot be applied, because
`walk_in_limit_kg` is a mass and a count of units is not. The member stays eligible
and the record says the weight was not established.

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
