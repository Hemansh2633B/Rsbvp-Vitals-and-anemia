# Taking a measurement session

A short guide for someone using RSBVP, not developing it. It describes what the
screen shows and what it does not mean.

> RSBVP is a research prototype. The number it gives you is an estimate from a phone
> camera. It is **not** a medical measurement, a diagnosis, or a substitute for a
> pulse oximeter, a heart monitor, or a clinician.

---

## 1. Before you start

The screen lists four things, each with its own state:

| Item | What you want to see |
|---|---|
| Camera | available (or the reason it is not) |
| Face detection | will start when you press Start |
| Face regions (ROI) | tracked once your face is found |
| Signal quality | acceptable |

If the camera line is red, the message tells you why — a denied permission, a
missing camera, or a page served over plain HTTP from a private address. Only the
first two are things you can fix by trying again.

**Setting up well matters more than anything else in this app.** Face a window or a
lamp so your face is evenly lit, with no strong light behind you. Fill a reasonable
part of the frame with your face — not tiny in the corner, not cropped. Then hold
still.

## 2. Collecting readings

Press **Start measurement**. The app analyses short windows of your face and keeps
the ones that pass its quality checks.

You will see:

- **Accepted** — windows that produced a usable reading.
- **Rejected** — windows that did not, with the reason.
- **Repeated** — windows the app already counted. These are not new information.
- A progress bar toward the number of readings a session needs.

You do not need to read a graph. If the signal is poor the screen says so and says
what to change: hold still, add light, keep your whole face in frame.

**Pause** stops recording without closing the camera, so you can sneeze or answer a
phone and then press **Resume** without starting over. Nothing is recorded while
paused.

## 3. Your result

When enough usable readings exist, the result becomes available and you can press
**Finish session**. You get:

- **Average pulse rate** — one number, in BPM. This is the session average.
- **Median** — the middle value. It barely moves when one reading is odd, so
  comparing it with the average tells you whether a single reading is pulling the
  average around.
- **Range** — the lowest and highest accepted reading, so you can see how much the
  readings moved.
- **Accepted** — how many readings the average rests on.
- **Session quality** — good, fair or poor. This describes *how much of what the
  camera delivered was usable*. It says nothing about accuracy.

### If your readings varied

You may see: *"Your readings varied during this session. Consider repeating the
measurement under steady conditions."*

That is not an error. It means the accepted readings disagreed with each other —
which is honest information about this session. The average is still shown, with
the variation included. Nothing was thrown away for differing.

### If there was not enough data

You may see: *"Not enough reliable readings were collected. Please try again."*

No number is shown, because a number from one or two windows would suggest a
precision that does not exist. The screen tells you what was missing — usually a low
accepted count, or readings that all came from the same short stretch of time. Press
**Start measurement** to retry, or **New session** to start clean.

## 4. Looking closer, and keeping a record

**View individual readings** expands a table of every window: when it happened, its
BPM, which face region and method produced it, whether the signal was acceptable,
and whether it was accepted, rejected (with the reason) or repeated. A `!` marks a
reading that differed considerably from the rest — those are *included* in the
average, not removed.

**Export readings (CSV)** gives one row per reading. **Export session summary
(JSON)** gives the full session: statistics, provenance, quality summary and the
settings used.

No camera frames or recordings are exported. Ever.

## 5. Starting again

**New session** clears everything — readings, counts, the result — and returns you
to Ready. The previous session is not carried over, and a new session's readings can
never be added to an old one's.

## 6. What this cannot tell you

The app deliberately does not report:

- a diagnosis, or any statement that your heart rate is healthy or unhealthy;
- HRV, RMSSD or SDNN — these need beat-to-beat timing that this method does not
  establish;
- respiratory rate as a measurement (it is inferred, labelled experimental, and kept
  out of the session result);
- blood pressure or oxygen saturation — not measurable from consumer RGB video;
- hemoglobin or anemia status — the anemia research pathway is separate and is not
  part of this workflow.

If you have a health concern, use a validated device and speak to a clinician.
