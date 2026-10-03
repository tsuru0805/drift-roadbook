# The drift protocol

A drift is three calls and a promise: the traveler goes alone, walks a while, and comes home with
something they wrote themselves.

## Lifecycle

```
start_drift ──► drift_act × 4..10 ──► finish_drift
     │                                     │
     └── unfinished drift exists? ◄────────┘ (missing travelogue → refused, drift kept)
            show it instead of setting off
     abandon_drift(confirm=True) — only the traveler can give one up
```

| Tool | Arguments | What happens |
|---|---|---|
| `start_drift` | `traveler`, `destination?`, `mood?` | Reads today's temperature (your `TemperatureSource` + `mood`), picks or resolves a destination, gathers sensory material from real travel writing, and returns the arrival scene. If this traveler has an unfinished drift, returns it instead (`ok=false`). |
| `drift_act` | `traveler`, `action` | One step, first person. Returns the next scene. From `MIN_ROUNDS` on, each reply ends with a hint that the traveler may come home; at `MAX_ROUNDS` the world stops advancing. If the narrator fails, nothing is recorded — send the same step again. |
| `finish_drift` | `traveler`, `travelogue`, `luggage`, `note?` | Both `travelogue` and `luggage` are required and are stored exactly as written; the engine only appends a record line under the travelogue. Below `MIN_ROUNDS`, or if either is missing, or storage fails: refused, drift kept. On success the drift is located and a photo is searched in the background. |
| `abandon_drift` | `traveler`, `confirm` | `confirm=true` required. Nothing is recorded. |
| `drift_status` | `traveler` | In progress? Also reports, once, whether the last drift's photo was found. |
| `read_drifts` | `traveler?`, `limit?` | Recent finished drifts. |

`luggage` may be "空手" / "empty-handed". Coming back with nothing is a souvenir too.

## Destinations

- **`destination` given** — used as given. The engine only narrows a vague wish down to a concrete
  spot *within what was asked* and fills in coordinates and search terms.
- **`destination` empty** — chosen from today's temperature: a small, specific place whose air,
  light and sound share today's texture. Recent *kinds* of places and times of day are passed in so
  the picks don't keep landing on the same sort of afternoon café.
- **Host mode** (`narrator=none`) — there is no model to choose, so a destination is required; the
  companion is told to pick one from how today feels.

## Narrators

| Mode | Who narrates | Cost |
|---|---|---|
| `claude-cli` | `claude -p` on your machine. One drift = one CLI conversation (`--session-id` then `--resume`); if the transcript is gone, history is replayed. API-key variables are stripped before every call. | your Claude subscription |
| `anthropic` | Messages API (`ANTHROPIC_BASE_URL` for a relay) | per use |
| `none` | your companion, in its own words, inside `drift_act` | free |

Web search (for sensory material) goes through the narrator. In host mode, material comes from
Wikivoyage / Wikipedia intros, and hits whose title doesn't overlap the destination are dropped.

## Location and photo

1. **Location** — Wikipedia coordinates, specific to general: the exact article, then with leading
   words dropped (a street → its district), each with Wikipedia's own search; finally the city.
   The result carries a `level`: `spot` / `street` / `city`. When only the city was found, the
   narrator's own estimate refines it if it lands within 30 km.
2. **Photo** — Wikimedia Commons, two tiers: (a) the spot — keyword search with the most specific
   photo query plus files geotagged within 600 m; (b) its street/district — the remaining queries.
   Filenames that are almost never a traveler's view (aerial, skyline, map, logo, apartment…) are
   dropped before anyone looks. A narrator that can see images then picks the one closest to the
   travelogue — or none. **No acceptable photo → no photo.** Credit and the file page are stored and
   shown with the image.

## Design commitments

1. **The traveler's words are the traveler's.** The engine never writes the travelogue or picks the
   luggage, and never edits what was written.
2. **A drift is never lost by accident.** Unfinished drifts persist per traveler across restarts.
   Every refusal leaves the drift exactly where it was. Only the traveler can abandon one.
3. **Every dead end says something.** Narrator down, storage failing, nowhere found, no photo —
   each receipt names the step and what to do next.
4. **A wrong picture is worse than an empty frame.**
5. **Two travelers can be out at once**, and several server processes can share one state directory.

## Tuning — our values, not rules

| Knob | Our value |
|---|---|
| Rounds | 4 – 10 |
| Luggage length | ≤ 30 characters |
| Travelogue minimum | 20 characters (only to catch an empty call) |
| Photo geosearch radius | 600 m |
| Photo candidates looked at per tier | ≤ 12 |
| City-level refinement radius | 30 km |
| Narrator model | `claude-sonnet-5-5`, effort `low` |

Decide yours together — ask your companion what feels right.

## Wiring it into your own house

Implement any of the four ports in `src/drift_roadbook/ports.py` / `prompts.py` and pass them to
`DriftEngine`:

```python
from drift_roadbook.engine import DriftEngine
from drift_roadbook.session_store import SessionStore
from drift_roadbook.narrators import ClaudeCLINarrator

engine = DriftEngine(
    storage=MyStorage(),                 # where drifts live
    store=SessionStore("/var/lib/drift-roadbook/state"),
    narrator=ClaudeCLINarrator(workdir="/var/lib/drift-roadbook/cli"),
    temperature=MyDiaryReader(),         # what "today" felt like
    reminder=MyTodoList(),               # keep a forgotten drift in sight
    prompts=MyPrompts(),                 # your companion's voice
    travelers={"aki": "Aki"},
)
receipt = engine.start("aki", destination="", mood="rainy, slow")
```

The engine is synchronous (the CLI narrator is a subprocess); call it from a thread in async code.
`Reminder.opened/closed` receive a stable key per drift — use it as an idempotency key for whatever
you create (a to-do, a pinned note) and close the same thing when the drift ends.
