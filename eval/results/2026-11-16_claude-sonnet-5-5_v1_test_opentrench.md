# Eval: OpenTrench3D views, frame mode (test)

date 2026-11-16 · commit eaadc9d · model claude-sonnet-5-5 · prompt v1 · split test · cases 15 · views 45 · cost_usd 0.4365 · wall_s 56.1 · pricing_as_of 2026-11-16

45 views (0 failed), 99 predicted lines, 0 views without other utilities (line-level judging).

## View level

| metric | result [95 % Wilson CI] |
|---|---|
| Area's utility visible: model named its type | 32/43 = 74% [60%-85%] |
| ... utility covers >= 1% of the image | 24/25 = 96% [80%-99%] |
| ... utility covers < 1% of the image | 8/18 = 44% [25%-66%] |
| Area's utility not visible: model still named its type (upper bound, see below) | 1/2 = 50% [9%-91%] |
| Model said 'no trench' | 0/45 = 0% [0%-8%] |

## All lines

| metric | result [95 % Wilson CI] |
|---|---|
| Lines left `unknown` (abstentions) | 35/99 = 35% [27%-45%] |
| Review rate: lines flagged | 79/99 = 80% [71%-87%] |

## Line level: only the 0 views without other utilities

64 lines with a concrete type are not judged because they are in a view with other utilities.

**Not measurable on this split.** Every view also shows untyped other utilities, so a line of another type cannot be told apart from a correct reading of one of them. Type accuracy, calibration and review recall/precision need views without other utilities.

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
