# Safety net: injected errors

Date 2026-11-15 · commit `b62fd75` · min_confidence 0.6 · size_tolerance 0.15

Each row corrupts one line of a clean, consistent report in one specific way and runs the deterministic verification (`verify_report`). No model calls, no labels: the injected error is the ground truth. This measures the **rules**, not the vision model; how often the model makes each kind of mistake is measured separately (OpenTrench3D eval).

- Detectable corruptions caught by the intended rule: **8 / 8**
- Findings on the clean report (false alarms): **0**
- Known blind spots (expected to pass unflagged): **2**

| corruption | what was changed | expected rule | rules that fired | result | false alarms on other lines |
|---|---|---|---|---|---|
| `wrong_type_vs_colour` | type changed so that it contradicts the observed colour (yellow pipe called water) | color_contradicts_type | color_contradicts_type | ✅ | 0 |
| `one_frame_disagrees` | one of three frames names a different type for the same line | conflicting_types | conflicting_types | ✅ | 0 |
| `overconfident_guess` | confidence lowered to 0.55 (a colour-only guess) | low_confidence | low_confidence | ✅ | 0 |
| `unknown_type` | type left unknown | unknown_type | unknown_type | ✅ | 0 |
| `unknown_material` | material left unknown | unknown_material | unknown_material | ✅ | 0 |
| `invented_size` | diameter reported although no frame has a scale reference | size_without_scale | size_without_scale | ✅ | 0 |
| `sizes_disagree` | scaled frames give 110 / 110 / 160 mm for the same pipe | size_inconsistent | size_inconsistent | ✅ | 0 |
| `phantom_line` | a line backed by a single frame of a video | single_frame_only | single_frame_only | ✅ | 0 |
| `wrong_type_ambiguous_colour` | black pre-insulated heating pipe called power, confidently (black means nothing) | — (blind spot) | — | ⚠️ not caught | 0 |
| `wrong_type_everywhere` | every frame consistently sees blue and says water, but the pipe is gas | — (blind spot) | — | ⚠️ not caught | 0 |

**Blind spots.** A wrong type is only caught when something contradicts it: a colour with a known convention, another frame, a low confidence. A confident wrong type on a black/grey pipe, or the same wrong reading repeated in every frame, passes every rule. Closing these needs a second, independent signal (warning tape text, an operator's network plan, or a second model run), not more rules over the same observations.
