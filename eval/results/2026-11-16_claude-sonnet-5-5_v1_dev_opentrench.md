# Eval: OpenTrench3D views, frame mode (dev)

date 2026-11-16 · commit eaadc9d · model claude-sonnet-5-5 · prompt v1 · split dev · cases 6 · views 18 · cost_usd 0.209 · wall_s 30.9 · pricing_as_of 2026-11-16

18 views (0 failed), 43 predicted lines, 4 views without other utilities (line-level judging).

## View level

| metric | result [95 % Wilson CI] |
|---|---|
| Area's utility visible: model named its type | 14/18 = 78% [55%-91%] |
| ... utility covers >= 1% of the image | 9/10 = 90% [60%-98%] |
| ... utility covers < 1% of the image | 5/8 = 62% [31%-86%] |
| Area's utility not visible: model still named its type (upper bound, see below) | n/a (0) |
| Model said 'no trench' | 0/18 = 0% [0%-18%] |

## All lines

| metric | result [95 % Wilson CI] |
|---|---|
| Lines left `unknown` (abstentions) | 15/43 = 35% [22%-50%] |
| Review rate: lines flagged | 29/43 = 67% [53%-80%] |

## Line level: only the 4 views without other utilities

22 lines with a concrete type are not judged because they are in a view with other utilities.

| metric | result [95 % Wilson CI] |
|---|---|
| Judged lines with the right type | 5/6 = 83% [44%-97%] |
| Wrong when confident (conf >= 0.8) | 0/3 = 0% [0%-56%] |
| Review recall: wrong lines flagged | 1/1 = 100% [21%-100%] |
| Review precision: flagged judged lines that are wrong | 1/2 = 50% [9%-91%] |

ECE 0.300 · Brier 0.111 (confidence = P(type correct), judged lines only)

| confidence | n | mean conf. | accuracy |
|---|---|---|---|
| 0.0-0.2 | 0 | - | - |
| 0.2-0.4 | 1 | 0.35 | 0.00 |
| 0.4-0.6 | 1 | 0.40 | 1.00 |
| 0.6-0.8 | 1 | 0.75 | 1.00 |
| 0.8-1.0 | 3 | 0.80 | 1.00 |

### Wrong lines (most dangerous first: not flagged, confident)

| view | predicted | conf. | verification |
|---|---|---|---|
| ot_h2_a2_s7_part_2 / right | wastewater | 0.35 | flagged |

## How views and lines are judged

- The area's utility is the area's main utility class, or its inactive class (old line of the same network), covering >= 0.2 % of the rendered view.
- A view counts as *found* when any line in the raw model output has the area's type. A failed model call counts as not found.
- *Not visible but named* is an upper bound: an untyped other utility in the view could be of the same type.
- Line level, only in views without other utilities: the area's type with its utility visible is correct, any other concrete type is wrong, `unknown` is an abstention. Mixing in views with other utilities would count every correct line and no wrong one, and inflate accuracy.

## Limits of this eval

- Views are renders of photogrammetric point clouds (black background, holes), not phone photos.
- Truth knows two utility types (water, district heating) plus untyped 'other utilities'.
- No line count in the truth (per-point classes, not instances).
- Data: CC BY-NC 4.0 (OpenTrench3D, Hansen et al. 2024). Denmark, not Switzerland.
