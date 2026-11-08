# 7. Classify restatements by their first material change

## Context
"The reported value changed" mixes three different things: a different XBRL tag (a different
measure), an amendment (a correction), and a later filing's comparatives (a recast, such as
discontinued operations). The latest report alone cannot tell them apart: a correction repeated
in later 10-Ks would look like a recast.

## Decision
mart_restatements classifies by the first report that materially changed the value, in order:
tag_switch (a different tag), correction (an amendment, form ending /A), recast (anything else).
A change of about 1,000x is flagged as a likely scale error (units mistake in the tagging).

## Consequences
- Of 328,872 restated facts: 62% recasts, 28% tag switches, 10% corrections. A naive count
  overstates corrections about tenfold.
- Confirmed by metric: cash and equity "restatements" are about two-thirds tag switches; metrics
  with a single mapped tag show exactly 0% tag switches.
- 3,048 likely scale errors (447 companies), e.g. a 10-K/A turning -$107m into -$107,322m.
