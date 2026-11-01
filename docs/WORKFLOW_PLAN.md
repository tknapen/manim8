# From a paper to a clip: work plan for the review loop

Status: proposed, 1 November 2026. Sections 2 and 9 hold decisions that belong to the author; the packages in
sections 3 to 8 are written so that the first of them can start before those decisions are taken.

The loop this plan codifies: a scientist drops in a PDF; a model reads it, extracts its figures and decides how
the topic can move on screen; it proposes a first storyboard, which the scientist edits and comments on; a first
implementation follows, whose keyframes the scientist checks and comments on; a fast render follows with another
round of comments; and so on until the scientist asks for the final render. The plan keeps the rule that has
governed the project from the start: the files are the state. A model's conversation is never the only copy of
anything, every change arrives as a validated proposal, and every approval names the revision and the image it
was given on.

## 1. What exists and what is missing

Most steps already exist as commands that read and write files, and `test_agent_loop` runs them from a brief to a
revision comparison with fixture proposals standing in for a model.

| Step of the loop | What exists | What is missing |
|---|---|---|
| A PDF comes in | `sources probe` (text per page, with page anchors); `scianim context` (a provider-neutral bundle) | figures, captions and page images; equations are cited by page only |
| The model proposes | `Proposal` files (patch operations, rationale, `in_response_to`, `uncertainties`, `claims`, `touches_science`); `propose validate` and `apply` | a typed interface an agent can call without a shell; a written playbook for the whole loop |
| A storyboard to edit | `storyboard.yaml`, validated | anything to look at before Manim renders |
| Keyframes | `codegen`, `snapshot`, `inspect`, the review view | nothing essential |
| Comments | `feedback add` and the review view (regions, objects, severity) | a reply: the agent's answer to a comment is a proposal or nothing |
| Next round | `propose from-feedback` for what rules can do; `revision create` | a record of which stage the project is in and whose turn it is |
| Fast render, final | `render --profile storyboard`, `draft`, `final`; the segment store redraws only what changed | a gate: nothing stops a final render of an unapproved revision |

Approvals exist for single checkpoint images (`feedback status`, bound to a revision and an image hash). There is
no approval of a storyboard, a set of keyframes or a draft, and no notion of a stage.

## 2. The shape of the boundary between the model, the package and the web interface

This is the part to settle first, because every package below depends on it.

### 2.1 Principles

1. **One operations layer, several faces.** Every action in the loop (read the status, read sources and figures,
   submit a proposal, answer a comment, request a render, approve) is one typed Python operation in the control
   plane. The CLI, the HTTP API behind the web interface and an agent interface are thin faces over it, so a person
   and a model can never do different things by the same name, and a rule enforced once is enforced everywhere.
2. **The model proposes; the person decides.** A model may read everything in the project and write proposals,
   answers, questions and requests for previews. It may not approve anything, apply a change that touches the
   science, render a final, write into a revision or run anything that is not a declared operation. The agent
   interface simply has no operation for those things.
3. **The conversation is made of records.** Comments are feedback records anchored to a checkpoint, a region, an
   object, a scene or a time range in a draft. The model's reply to a comment is an answer record in the same
   thread (addressed by a proposal, a question back, or declined with a reason). Threads are files, so they
   survive a change of model, of session or of person, and the web interface shows them where they were made. A
   free chat window, if there is one, is a way of writing such records, not a place where decisions live.
4. **The package never needs a model.** Validation, code generation, rendering and review work without one, as
   AGENTS.md requires. A model makes the loop faster; it is not part of the contract.
5. **No vendor in the format.** Proposals record an `author` string; nothing in a file depends on which model
   wrote it.

### 2.2 Where the model runs: two routes

**Route A: an external agent drives the package.** A coding agent (Claude Code, or any client that speaks the
Model Context Protocol) connects to a local agent server, `scianim mcp`, that exposes the operations layer as
tools and resources, or uses the CLI directly. The scientist reviews and comments in the web interface and tells
the agent, in its own session, to take the next turn ("address the open comments on rev_0004"). The model, its
keys and its cost belong to the client; the package holds no credentials.

**Route B: the web interface calls a model.** The review server runs an agent turn as a job, like a render, when
the scientist presses a button ("address these comments", "propose a storyboard from the sources"). A provider
adapter calls a model API with the same tools; the turn has a log, a cost estimate, a cancel button and a result,
which is the proposals and answers it wrote. Keys come from the environment or the operating system's keychain,
never from project files.

Recommendation: build A first and B on top of it. A needs no keys, no cost control and no new trust boundary, and
it exercises exactly the tools B will use; B is then a loop around the same operations plus a provider adapter.
Under both routes the web interface is the scientist's surface and the files are the record.

### 2.3 The agent's tools and resources

Resources (read): the project status (section 3); the sources with their text, figures and captions; the
component registry with parameter schemas; the resolved style; the current specification and storyboard; open
feedback threads with their images; the latest inspection and layout reports; any rendered checkpoint as an
image, so a model that can see compares the picture with its description.

Tools (write or act):

| Tool | Effect | Limits |
|---|---|---|
| `propose` | writes a proposal (spec, storyboard, custom builder) after validating it | a change that touches the science is marked and waits for sign-off |
| `answer` | writes an answer record in a feedback thread, optionally naming a proposal | none |
| `ask` | adds an uncertainty the model cannot settle from the sources | none |
| `apply` | applies a proposal the project's policy allows the agent to apply on its own | refused for science and for anything the policy reserves |
| `preview` | renders named checkpoints or a storyboard-profile draft | storyboard, snapshot and draft profiles only |
| `inspect` | compares rendered checkpoints with their descriptions and layout rules | none |

There is no tool to approve, to render a final, to create or alter a revision, or to run code outside the family
environment's render worker.

### 2.4 How much the model may do on its own

A project-level policy file (`agent.yaml`, versioned with the project) sets what `apply` may do without the
scientist: by default nothing; a common setting lets the agent apply visual and timing changes (layout, durations,
easing) and render previews, while anything that touches equations, data, sources, claims or custom code waits for
acceptance in the web interface. Science always waits for sign-off, whatever the policy says.

### 2.5 What the web interface becomes

It is where the scientist sees what is waiting on whom, reads the model's proposals as diffs with their rationale
and the comments they answer, accepts or rejects them, answers the model's questions, comments on cards,
checkpoints and moments of a draft, approves stages, and starts renders. Under route B it also starts agent
turns. It never runs generated Python and never holds the only copy of a decision.

## 3. Package I: stages, approvals and gates

**Scope.** A derived project status: `scianim status <project>` and `GET /api/projects/{id}/status`, computed from
the files (revisions, feedback, proposals, manifests), never stored. It reports the stage (sources, specification,
storyboard, keyframes, draft, final), the revision under review, open threads and questions, pending proposals,
approvals and what invalidated them, and the next action with its owner (scientist or agent).

**Contracts.** Stage approvals extend today's `kind: status` feedback records with a scope: `storyboard`,
`keyframes`, `draft` (and the existing checkpoint scope), each bound to a revision and, for images and videos, a
content hash. Invalidation follows the scene fingerprints of ADR-033: a revision whose fingerprint for a scene
differs from the approved one invalidates that scene's approvals; a change that touches the science invalidates
the scientific sign-off of the scenes it reaches (spec 9.3). `render --profile final` refuses a revision without
an approved draft, unless `--override "<reason>"` is given, which is recorded in the manifest.

**Tests.** Status derivation over a scripted history (unit); invalidation by fingerprint (unit); the final gate and
its recorded override (integration); the status banner in the web interface (browser test).

**Acceptance.** On the orientation example, the status moves from storyboard to final through recorded approvals,
and a change to one scene after the draft was approved reopens that scene alone.

## 4. Package J: figures and equations from PDFs

**Scope.** `sources probe` renders page images and extracts embedded figures with their captions (the text block
beginning "Fig." or "Figure" nearest each image), giving each an id such as `fig:p4-2` and a page anchor, under
`.scianim/sources/<source>/figures/`. The context bundle and the agent's resources include them as images. A figure
used by a storyboard declares its role (composition reference, style reference, redrawn from data, reinterpreted;
spec 6.3). Equations are read by the model from the page or figure image and transcribed into the typed
`equations` field with a locator (page, equation number); every such equation touches the science and waits for
sign-off.

**Choices.** `pypdfium2` (Apache 2.0/BSD) for page rendering and image extraction, not PyMuPDF (AGPL). Extracted
figures are evidence for the model and the scientist; they never enter an exported bundle (spec 6.3, AGENTS.md).

**Tests.** A small fixture PDF with two figures and captions: ids, anchors, captions and images are extracted; a
scanned page yields a page image and a note that no text was found.

## 5. Package K: the storyboard sheet

**Scope.** Something to look at and comment on before Manim renders: one card per scene with its narration, its
objects (kind, data source, equation), its actions on a time line, its checkpoints with their descriptions, and
the figures it draws on, in the web interface and as static HTML. The sheet is labelled a mockup, as AGENTS.md
requires of anything that is not a Manim render. Comments on a card are feedback records anchored to the scene,
an object or an action.

**Alternative.** Treat storyboard-profile snapshots (one to three minutes for the examples) as the storyboard
review and skip the sheet. Cheaper to build and shows real pictures; the sheet lets the narrative be fixed before
any render and costs nothing per round. The two can coexist: sheet first, snapshots once the order is settled.

**Tests.** The sheet of each example renders; a card comment validates as a feedback record anchored to its scene.

## 6. Package L: the agent interface and the playbook

**Scope.** The operations layer of section 2.1 extracted from the CLI and API code; `scianim mcp`, a local
(stdio) Model Context Protocol server exposing the tools and resources of section 2.3; answer records
(`kind: answer`, with `in_reply_to`, `outcome` addressed / question / declined, optional `proposal`); the policy
file of section 2.4; and the playbook: for each stage, what the agent reads, what it produces, which operation
checks it, and the rule that it stops and asks at an unapproved gate. The playbook ships inside the context bundle
(provider-neutral) and as a Claude Code skill in the repository, and the tutorial follows the same steps.

**Tests.** A scripted agent (fixture tool calls, no model) drives a project from sources to an approved draft
through the server; the server has no approve or final operation; the policy refuses an `apply` it reserves; an
answer record threads under its comment in the API.

**Acceptance.** Spec Phase 4's gate: from a prompt and example data an agent builds a valid specification and
storyboard, generates named checkpoints and applies one region-specific revision with a traceable diff, here
through the agent server.

## 7. Package M: agent turns from the web interface (route B)

**Scope.** A provider adapter interface (one implementation first, others behind the same interface), a job type
`agent_turn` run by the server's job runner with a log, a cost estimate before it starts, a cancel button and a
result listing the records it wrote; buttons in the review views to start a turn on the open comments of a
revision or on a stage. Keys from the environment or the keychain, never from project files.

**Starts after** package L, and only if route A proves too slow in daily use.

## 8. Package N: the tutorial

**Scope.** One end-to-end tutorial, from a PDF to a final clip with two rounds of comments, written against the
real commands and run in CI as an acceptance test with recorded proposals standing in for the model, so CI needs
no model access. A second, shorter page for agents: the playbook as prose.

**Needs** a paper chosen by the author (section 9).

## 9. Order, and what remains with the author

Order: I first, since the status and the gates are what the playbook and the interface rest on; J and K in
parallel with it; L once I has landed; N last; M only if the daily use of route A asks for it.

Decisions for the author:

1. The route for the model: A first and B later (recommended), B first, or A only.
2. The storyboard review: the sheet, low-resolution snapshots, or both in that order.
3. The default policy for what the agent applies on its own.
4. Threads only, or threads with a chat panel that writes records.
5. The paper for the tutorial, and whether its figures may be shown in published material.

Risks worth naming: the component registry bounds what a model can make without writing Python, and custom
builders are where quality and safety risks concentrate, so they get their own review and tests; equations read
from images are the likeliest place for a silent scientific error, hence their mandatory sign-off; and a
model's cost per round grows with the paper and the images it is shown, which route B must display before a turn
starts.
