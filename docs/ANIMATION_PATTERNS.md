# Animation patterns: what a corpus and the studies say, and the library built from them

Status: first version, 2 November 2026 (ADR-040); cues and partial ink added the same day (ADR-041). The library
itself is data in [`patterns/`](../patterns/);
`scianim patterns list`, `show` and `check` read it, and the agent's context bundle carries it.

The question was which transitions, animations and dynamics serve a short scientific clip, so that an agent
choosing how a scene moves starts from idioms that have worked, not from whatever the registry happens to
allow. Two sources of evidence answer different parts of that question. A large corpus of explanatory
animation shows what an experienced author does and how he times it; it cannot show what viewers learn from.
Experiments on learning from animation show where animation helps and where it misleads; they say little about
staging in particular. The library keeps the two apart in every entry.

## 1. Method

**Corpus.** The scene code of the 3Blue1Brown videos, [3b1b/videos](https://github.com/3b1b/videos) at commit
`306a134` (29 September 2026), licensed CC BY-NC-SA 4.0. Nothing from it is copied into this project: the
library records counts and the names of scenes, and describes idioms in its own words. The year folders
`_2015` to `_2026` hold 375 Python files; 3 do not parse as Python 3 (two from before 2020) and were skipped.

**Counting.** [`tools/survey_corpus.py`](../tools/survey_corpus.py) parses every file with `ast` and runs none
of it. A scene is a class with at least one `self.play` call: 4,814 scenes with 30,103 plays. Each argument of
a play becomes a token (an animation class, an `.animate` method, a value-tracker sweep, a camera move), and
each scene gets idiom flags from its tokens and from constructs such as value trackers, updaters, traced paths
and colour-linked terms. The output, [`patterns/survey/3b1b_videos.json`](../patterns/survey/3b1b_videos.json),
gives shares per era (2015-2019, 2020-2022, 2023-2026), timing statistics and exemplar scenes; a unit test runs
the script on a small synthetic corpus.

**Reading.** Twenty-two exemplar scenes, chosen from well-known projects for one idiom each, were read in full
to check what the counts mean and to find habits the counts miss. Three only partly fit their label; the
descriptions were spot-checked against the code before use.

**Studies.** Meta-analyses and experiments on learning from animation, on animated transitions in charts and
on attention cues, listed in [`patterns/references.yaml`](../patterns/references.yaml). Their full texts could
not be fetched from this environment (the publishers' hosts are outside its network policy), so each was
checked against its abstract and bibliographic record only, and each entry says so.

## 2. What the corpus does

Share of scenes that use an idiom, in percent, by era (1430 scenes in 2023-2026):

| idiom | 2015-2019 | 2020-2022 | 2023-2026 |
|---|---|---|---|
| fade in or out | 54.9 | 65.1 | 57.8 |
| draw on (stroke or write) | 69.9 | 61.5 | 52.6 |
| staggered group | 20.1 | 34.1 | 34.5 |
| morph (transform, replace) | 43.9 | 38.5 | 31.3 |
| characters (pi creatures) | 30.2 | 26.7 | 24.3 |
| updaters | 7.9 | 19.2 | 19.9 |
| colour-linked terms | 17.5 | 23.9 | 17.5 |
| derive by copy | 4.3 | 16.3 | 16.9 |
| surrounding box | 9.5 | 21.0 | 16.9 |
| flat camera move | 0 | 3.9 | 16.1 |
| parameter sweep | 4.5 | 10.2 | 13.6 |
| 3D camera move | 0 | 4.0 | 12.5 |
| random samples | 6.3 | 15.2 | 12.3 |
| dim the rest | 4.0 | 5.7 | 11.9 |
| rewrite with matching parts | 0 | 7.3 | 9.8 |
| one value drives several objects | 2.1 | 4.9 | 8.8 |
| number readout tied to a value | 3.2 | 8.0 | 5.2 |
| trail of a moving point | 0.1 | 0.5 | 2.0 |
| space transformation | 3.2 | 0.9 | 0.6 |

Per play, the change over eleven years is larger than per scene. `TransformFromCopy`, which sends a copy of a
part to where it is used next, rose from 19 to 93 occurrences per 1,000 plays and is now the most frequent
transform. Value-tracker sweeps rose from 13 to 67 plays per 1,000, camera moves from none to about 131, grouped
and staggered plays from 64 to 152. Drawing strokes on fell from 326 to 219. The direction is from drawing a figure piece by
piece towards driving a figure from values and moving the viewpoint while it changes.

**Timing.** The default play lasts 1 s, and most discrete changes keep it. Among single-kind plays of
2023-2026 (with the default counted as 1 s):

| kind of play | plays | run time given (%) | median (quartiles), s | median when given, s |
|---|---|---|---|---|
| fade | 1077 | 10 | 1 (1-1) | 2 |
| draw on | 712 | 24 | 1 (1-1) | 2 |
| morph | 314 | 34 | 1 (1-2) | 2 |
| rewrite with matching parts | 114 | 47 | 1 (1-1) | 1 |
| derive by copy | 131 | 24 | 1 (1-1) | 2 |
| indication | 118 | 44 | 1 (1-2) | 2 |
| move | 180 | 67 | 2 (1-4) | 3 |
| parameter sweep | 285 | 86 | 3 (2-5) | 3 |
| flat camera move | 60 | 85 | 2.75 (2-5) | 3 |
| 3D camera move | 200 | 98 | 7.45 (4-12) | 8 |

Discrete changes take about a second, continuous ones three to eight. Waits last 1 s at the median (mean 1.9 s).
Staggered groups use a lag ratio of 0.15 at the median (quartiles 0.1 and 0.5). Only about 4% of plays name a
rate function; the rest keep their animation's default, for most animations a slow-in, slow-out curve with
zero first and second derivatives at both ends. Among named ones in 2023-2026, `linear` is the most common (15
per 1,000 plays), then `there_and_back` (8), the out-and-back sweep. A scene has 3 plays and lasts about 8 s at the median (quartiles 4 and 17 s), counting
literal run times and waits, which is the length of one of this project's clips.

**What reading added.** The exemplar scenes show habits the counts do not separate:

- a sweep runs 2 to 3 s and is followed by a 1 s hold, and stretches to 4 to 10 s when the viewer has to follow
  a readout as it changes;
- a camera move usually shares its window with a change of content, offset so that one leads the other;
- a faint copy of the old state (a grey grid, a path at 0.4 opacity) stays while the object changes;
- a highlight box travels from a symbol in the formula to the thing it names;
- what is not yet in play sits under a dark translucent cover;
- two representations of one quantity are joined by a line that follows the value;
- many items collapse into the one number they add up to;
- in scenes that keep time running, holds carry motion, and time is frozen while a coefficient changes.

## 3. What the studies say

Animation helps learning on average, but modestly and conditionally. Across 26 studies, animations beat static
pictures by d = 0.37, more when they depict the change to be learned than when they decorate (Höffler and
Leutner, 2007). A later meta-analysis found g = 0.226 overall, larger for system-paced animation, with spoken
commentary, or without accompanying text (Berney and Bétrancourt, 2016). Re-analysed by what learners had to
learn, the benefit appears when the features of a change must be learned (g = 0.34 for simple features, 0.65
for complex ones) and vanishes when they need not be (g = 0.04; Ploetzner, Berney and Bétrancourt, 2020). In an
experiment on a gear mechanism, the animation group identified motions best and the picture groups identified
spatial arrangements best (Ploetzner et al., 2021).

The reasons animations fail are perceptual. A graphic should correspond to the concept it conveys and be
perceived accurately; animations satisfy the first for change over time and often fail the second, being too
fast or too complex, and many apparent advantages came from comparisons that did not carry the same
information (Tversky, Morrison and Bétrancourt, 2002). Learners attend to what is salient rather than what is
relevant (Lowe, 2003), and cues that signal the relevant information improve learning (d = 0.38; Alpizar,
Adesope and Wong, 2020). For transitions between charts, animation improved the perception of changes, and
staged transitions, one aspect at a time, were preferred (Heer and Robertson, 2007); staggering the start of
many moving objects did not help viewers track them and may hurt (Chevalier, Dragicevic and Franconeri, 2014).
Slow in and slow out, the default easing of the style, is one of the principles of hand-drawn animation
(Lasseter, 1987).

For a clip of 5 to 30 seconds, the conditions translate directly: animate what changes and must be learned,
keep everything else still, cue the change before it happens, change one thing at a time unless the
interaction is the point, and leave time to see the result.

## 4. From evidence to the library

An idiom became a pattern when the corpus uses it in a measurable share of scenes, or reading found it
recurring, and when it serves a function the studies speak to: showing a change that must be learned,
directing attention to the relevant part, or keeping the correspondence between two states or two pictures.
Two idioms were left out. Characters (in more than a quarter of all scenes) are the channel's narrative device,
outside this project's mission. Flip-book stepping with instant changes reads as a slide sequence.

| pattern | group | status | recipe (example scene) |
|---|---|---|---|
| `sweep_with_readout` | change | available | divisive_normalization / normalization |
| `staged_terms` | change | available | gabor_filter / gabor |
| `linked_views` | change | available | orientation_tuning / model |
| `rewrite_with_matching_terms` | form | available | drop_impact / splash |
| `release_the_scaffolding` | attention | available | gabor_filter / gabor; drop_impact / splash |
| `orbit_to_reveal_depth` | viewpoint | available | prf_tuning / prf |
| `let_time_run` | motion | available | drop_impact / splash |
| `motion_under_a_law` | motion | available | drop_impact / splash |
| `signal_before_change` | attention | available | orientation_tuning / model; gabor_filter / gabor |
| `dim_the_context` | attention | available | orientation_tuning / model |
| `reveal_in_reading_order` | attention | partial | orientation_tuning / circuit |
| `sliding_window` | motion | partial | none |
| `derive_by_copy` | form | planned | |
| `morph_between_representations` | form | planned | |
| `map_a_space` | form | planned | |
| `keep_a_ghost` | form | planned | |
| `zoom_to_detail` | viewpoint | planned | |
| `trace_the_path` | motion | planned | |
| `samples_accumulate` | chance | planned | |

Each entry gives when to use the pattern and when not, its beats in order, its usual durations (from the
timing above), its pitfalls (most of them from the studies), and its corpus evidence with exemplar scenes.

## 5. What the registry lacks

The partial and planned patterns name what is missing. Ordered by how much a scientific clip would gain and
how often the corpus relies on the idiom, a proposal for the author:

1. Done (ADR-041): an `emphasize` action for any object or equation term without a sweep, a box that can travel
   from a symbol to what it names, or a pulse; the cue of `signal_before_change`, in 11 to 17% of recent scenes.
2. Done (ADR-041): fading to a given ink level rather than out (`dim_the_context`, 12%).
3. Sending a copy of a term or picture element into another equation (`derive_by_copy`, 17%, the most
   frequent transform of recent years).
4. Staggered and stroke-drawing reveals within one object (`reveal_in_reading_order`; staggering in 35% of
   recent scenes, drawing on in 53%).
5. Trails (`trace_the_path`), for trajectories, phase portraits and scan paths.
6. A flat camera that zooms to a region and back (`zoom_to_detail`, 16%).
7. Shaded areas and a traced running integral (`sliding_window`), for convolutions and receptive fields.
8. Illustrative samples into a histogram (`samples_accumulate`, 12%).
9. Ghosts of an earlier state (`keep_a_ghost`), morphs between components (`morph_between_representations`)
   and maps applied to a grid (`map_a_space`, which retinotopy would need), each a larger piece of work.

## 6. Limits of this evidence

The corpus is one author's, made for long narrated lectures with recurring characters; its idioms are what he
reaches for, not what has been shown to work, and shares depend on the topics of each year (the linear-algebra
series puts space transformations in 2016). Counts come from code, not from rendered frames: a scene in the
code may never have been used, run times count only when written as literals, and some flags are heuristics
(dimming counts opacity changes made in place; flat and 3D camera moves are told apart by the angles of a
`reorient`). The studies were checked against abstracts only, report averages over heterogeneous materials,
and rarely concern clips as short as these. The timing ranges in the library are guides for a first proposal,
to be judged on the keyframes and the draft.

## 7. Reproducing

```bash
git clone --depth 1 https://github.com/3b1b/videos /path/to/videos
python -I tools/survey_corpus.py /path/to/videos patterns/survey/3b1b_videos.json
scianim patterns check        # entries, references, surveyed idioms and recipe scenes agree
scianim patterns show sweep_with_readout
```
