# Survey: lessons from code-first design languages, for pkidl

Scope: the "design languages" half of charter step 2. Researched 2026-11-11 from
primary sources (project docs, specs, source code, issue trackers, papers,
maintainers' own posts). Anything not confirmed from a primary source is marked
**unverified**. MyHDL was not researched.

---

## 1. CadQuery vs build123d

**CadQuery** is a fluent, jQuery-style chain over a hidden `Workplane` stack.
Its stated goal: "Build models with scripts that are as close as possible to how
you'd describe the object to a human", via "A fluent API to create clean, easy
to read code" (https://cadquery.readthedocs.io/en/latest/intro.html).

```python
pillow_block = (cq.Workplane("XY").box(h, w, t).edges("|Z").fillet(f).faces(">Z").workplane() ...)
```

Pain, from CadQuery's own primer: the chained style "is then more difficult to
debug as you cannot visualize each operation step by step", and chaining
pending geometry needs an explicit `toPending` call
(https://cadquery.readthedocs.io/en/latest/primer.html).

Selectors are a string mini-language: `">Z"`, `"|Z"`, `"#Z"`, `"%Plane"`,
`">Y[-2]"`, combinable with `and/or/not/exc`. The documented limits: non-planar
faces are judged at their centre of mass, and "Non-linear edges are never
returned when these filters are applied"
(https://cadquery.readthedocs.io/en/latest/selectors.html).

**build123d** keeps the OpenCascade kernel and replaces the chain. Its docs
give the reasons (https://build123d.readthedocs.io/en/latest/introduction.html):
- "the most significant advantage is that build123d is more pythonic";
- "the replacement of method chaining (fluent programming) with a standard
  python context manager", so `for` loops and `print` work inside a model;
- every object and operation is a class instance that can be assigned and
  inspected (`r = Rectangle(w, h); print(r.area)`);
- extensions are new classes "without monkey patching", so they show up in IDEs;
  enums let IDEs "prompt users for valid options without having to refer to
  documentation";
- "string based selectors have been replaced with standard python filters and
  sorting": `rail.faces().filter_by(Axis.Z)[-1]`.

build123d has two modes:
- **Builder mode** (`with BuildPart() as p:`): "objects add themselves to the
  active builder immediately when they are created"; the target builder is
  chosen "from the scope of the object". The same page warns about the result:
  "Because the cylinder was already added to the builder, the move operation
  has no effect on the model being built"; "Placement must therefore be
  specified before the object is created"; and "A builder created inside a
  function is not part of the build that called the function"
  (https://build123d.readthedocs.io/en/latest/key_concepts_builder.html).
- **Algebra mode**: plain objects and operators. `Box(1,2,3) - Cylinder(0.2,5)`;
  `Plane.XZ * Pos(1,2,3) * Box(1,2,3)`; `GridLocations(4,4,2,1) * Circle(0.25)`.
  An object "defines its topology ... but does not know where in space it will
  be located", so placement is a separate operator. Builder contexts "are not
  shapes and therefore cannot be combined directly with algebra operators"; you
  extract `.part` first
  (https://build123d.readthedocs.io/en/latest/key_concepts_algebra.html).

Selector fragility persists in both: build123d's tips page shows a selection
where "the position of the circle randomly switches between the bottom and top
corner", and a "top right" selection that "would likely change if the sketch
was ever moved" (https://build123d.readthedocs.io/en/latest/tips.html).

**Lesson for pkidl.** The move away from CadQuery was away from *a hidden
stack*, not toward *a context manager*: build123d's builder mode still carries
an ambient "active builder", and its own docs list the pitfalls that causes.
Algebra mode (values plus operators, placement separate from shape) is the one
that matches the charter's "explicit objects, no hidden state". Selectors as
typed Python queries beat a string mini-language for IDE and agent discovery;
geometry-based selection is fragile, so pkidl should select by *logical*
identity (refdes, net, pin), which it has and CAD does not.

## 2. OpenSCAD

Purely declarative CSG: the program evaluates to a CSG tree and geometry is
computed afterwards, so the program cannot read back what it built. Users on
the OpenSCAD list: "There is no way to get any polygon geometry data with
OpenSCAD language unless you have generated its vertex list" (2018-02-12,
https://lists.openscad.org/empathy/thread/W3JED45AASVQ47M6PIEX25V3MFVJYUNL);
"this is not possible currently as the points are not available internally
until the object is rendered" (2017-01-25,
https://lists.openscad.org/empathy/thread/JQ4TZSQXZW4KO7JTDJDPUQ5X346YZGVX).
The proposal to fix it (geometry literals plus `render()` returning
`min/max/center/size` and mesh data) is PR #4478, still open and marked stale
in 2026 (https://github.com/openscad/openscad/pull/4478).

What CadQuery users cite for leaving it: a standard language and its
infrastructure, a stronger kernel (OpenCascade vs CGAL), STEP/DXF in and out,
less code, faster export (https://cadquery.readthedocs.io/en/latest/intro.html).

Agent evidence: ModelRift ran six Claude agents on three parts in each tool,
judged by an independent STL checker. Totals OpenSCAD vs CadQuery: tool-raised
errors 2 vs 5, silent wrong geometry 5 vs 4; "Of the 16 failures, 9 were never
mentioned by the tool". CadQuery could query its own B-rep and `assert` on it;
both OpenSCAD agents had to write STL parsers to measure their own output.
CadQuery's errors were still poor ("BRep_API: command not done", naming neither
edge nor radius), and both tools self-certified broken geometry. Renders caught
only coarse blunders; numeric checks caught the print-ruining defects
(https://modelrift.com/blog/cadquery-vs-openscad/). One agent per cell, so the
spread includes agent variance (the author's own caveat).

**Lesson for pkidl.** Queryability is not a convenience: without it an agent
builds its own measuring tools. And a kernel that reports success on wrong
output is the common case, not the edge case: the verdict must come from an
independent measurement (for pkidl, KiCad DRC plus the layer-4 intent
measures), not from the builder's own "ok".

## 3. SKiDL

Syntax (https://devbisme.github.io/skidl/):
```python
vin += r1[1]                                  # "+= is the only way to make connections!"
ser = vcc & r1 & r2 & gnd                     # series
par = vcc & (r1 | r2 | r3) & gnd              # parallel
```
Parts and nets go into "a global instance of a `Circuit` object called
`default_circuit`" unless a `circuit=` or `with my_circuit:` says otherwise;
"You can't make connections between parts, nets or buses that reside in
different `Circuit` objects". Subcircuits are `@subcircuit` functions, an
`Interface` return, a `SubCircuit` subclass (with a "DO NOT USE
super().__init__()!" warning), or a `SubCircuit` context manager, of which "re-using
a group is not possible".

Pain points from the tracker:
- **The global default breaks explicit use.** #86: a user writing "code that
  modifies as little global state as possible" found `@package` assumed
  `default_circuit` and failed with `Can't attach nets in different circuits`;
  the feature was later removed (https://github.com/devbisme/skidl/issues/86).
- **The global default breaks tooling.** #168: a file-watching visualiser and CI
  needed SKiDL as a compiler, but "this all kind of rely on the global circuit
  objects being the ones used, and it breaks the logging outputs and file
  names"; they asked to "seperate the compilation parameters ... from the
  circuits source code" (https://github.com/devbisme/skidl/issues/168).
- **Composability.** #48: a subcircuit could not stand in for a part ("the
  Circuit interface is nothing like the Part interface"); the maintainer: "The
  Circuit object didn't come along until the latter part of SKiDL development.
  It was kind of a grab-bag of pieces" (https://github.com/devbisme/skidl/issues/48).
- **Unstable identity.** #238: auto-assigned references shift when code is
  reordered, so KiCad re-import loses the link to placed footprints; the fix
  was UUID timestamps plus a warning "for each part that doesn't have a
  manually-assigned tag" (https://github.com/devbisme/skidl/issues/238).
- atopile's authors, on why they did not build on SKiDL: "the language would let
  users do things like create a component and not hold a reference to it"
  (https://news.ycombinator.com/item?id=39263854).

**Lesson for pkidl.** SKiDL's terseness is the bar the charter sets, but each
pain point above traces to implicit global state or to identity derived from
execution order. pkidl's board must be an explicit object passed in, IDs must
be stable under code reordering (from the netlist's refdes/tag, never from
creation order), and a block (the layout analogue of a subcircuit) must be a
first-class reusable value from day one, not added later.

## 4. Python-embedded HDLs: Amaranth, Chisel

**Separation of elaboration from output.** Amaranth defines elaboration as "The
process of creating a data structure representing the behavior of a complete
design"; `elaborate(platform)` returns a `Module`, and Amaranth code
"_describes_ computations on abstract objects"
(https://amaranth-lang.org/docs/amaranth/latest/guide.html). Chisel elaborates
to FIRRTL, which a compiler lowers to Verilog; `Definition(...)` "enables
elaborating a module, but does not actually instantiate that module", and
`Instance(defn)` places it, so a block is elaborated once and placed many
times (https://www.chisel-lang.org/docs/cookbooks/hierarchy).

**Errors that point at user source.** Amaranth captures a source location at
construction (`tracer.get_src_loc`) on every fragment and statement, and uses it
in errors, e.g. `Domain ... required by {fragment_name} at {file}:{line}`
(`amaranth/hdl/_ir.py`, https://github.com/amaranth-lang/amaranth). It infers
signal names from the assigned variable (`tracer.get_var_name`, `_ast.py`).
Chisel added a compiler plugin because "Historically, Chisel has had trouble
reliably capturing the names of signals"
(https://www.chisel-lang.org/docs/explanations/naming). Chisel emits
`@[File.scala line:col]` locators into FIRRTL, and offers `--no-source-info` to
drop them (https://www.chisel-lang.org/api/latest/chisel3/stage/SuppressSourceInfoAnnotation$.html):
source locations and stable output are in tension.

**Guarding the embedding's sharp edges.** Amaranth turns a known Python trap
into a corrective error: `` `if m.If(...):` does not work; use `with m.If(...)` ``
(`amaranth/hdl/_dsl.py`). Every `Elaboratable` is "must-use": one that is
garbage-collected without being elaborated warns `... created but never used`
at its construction site (`amaranth/_unused.py`). This is the exact SKiDL
failure atopile named above.

**What Amaranth changed and why.** Releases are RFC-driven
(https://amaranth-lang.org/docs/amaranth/latest/changes.html). 0.4 replaced
`Record` with `lib.data` and `lib.wiring` (RFC 1, 2) and made signatures
immutable (RFC 37, 38). 0.5 removed upward propagation of clock domains (RFC 59):
"a clock domain created anywhere in the hierarchy is, by default, propagated
everywhere", "The default behavior constitutes the ultimate implicit spooky
action at a distance. It is also rarely used"
(https://amaranth-lang.org/rfcs/0059-no-domain-upwards-propagation.html). 0.5
also made no-argument `m.Case()` never active (RFC 39), renamed `reset=` to
`init=` (RFC 43), stopped accepting non-`Elaboratable` objects, and deprecated
`Settle` and generator testbenches. The direction across both releases is
removing implicit behaviour and making interfaces typed and immutable.

**Lesson for pkidl.** Build an IR, then emit KiCad: never write the board file
while user code runs. Record the user's file:line on every intent object and
put it in every diagnostic. Turn known misuse into an error that names the fix.
Warn on any intent object created but never attached. Elaborate a block once,
place it per instance. Keep source locations out of the emitted `.kicad_pcb`
(or opt-in), so "same input, same bytes" survives a file move.

## 5. atopile: its own language

What the authors said, Show HN, Feb 2024 (https://news.ycombinator.com/item?id=39263854):
- "Building a DSL allows us to keep it really simple to start, we tried using
  SKIDL", and the SKiDL reference-dropping problem quoted in section 3;
- "Baking a description of a circuit into python describes how to obtain the
  circuit", not the circuit itself;
- Python is "procedural, turing complete and has a rich eco-system", leaving no
  standard composable patterns: "Instead of describing your board, you
  (practically) write a script that generates your board";
- units and tolerances as first-class syntax, awkward in a Python string or
  constructor; "most EEs we've worked with were a bit put off by the syntax";
- on layout: "I think with few exceptions defining explicit layout choices in
  our language will be painful and not the right path"; layout reuse is captured
  from KiCad and shipped with the ato code.

User pushback in the same thread: "very unlike what is normally used
(s-expressions) in EDA"; "Why not use Verilog or SystemVerilog?"; "what happens
when the user needs to tweak the layout for some unique requirement?"

Where it ended up: the `.ato` DSL is now one front end onto a Python object
model. "The ato compiler is responsible for converting the ato DSL into a
faebryk type-graph", via an ANTLR4 parser "pending bespoke lexer/parser"
(https://github.com/atopile/atopile/blob/main/src/atopile/compiler/README.md);
`fabll` is "the high-level Python API for defining and working with hardware
components", and the compiler "Generates `Node` subclasses dynamically from
`ato` files" (https://github.com/atopile/atopile/blob/main/.claude/skills/fabll/SKILL.md).
So atopile is, in effect, two authoring surfaces over one model.

**Lesson for pkidl.** atopile's reasons for a language are real (references
dropped silently, imperative scripts, units), but each one has an in-Python
answer that section 4 shows working: must-use warnings, an IR that the script
only builds, typed unit values. The cost of its own language is a parser and
toolchain to maintain (still on ANTLR), a learning cost users objected to,
and, for agents, a low-resource language (section 8). Its own users' layout
question ("tweak the layout") is pkidl's coverage layer.

## 6. Constraint layout: CSS, Auto Layout, Cassowary

**Cassowary** solves "Linear equality and inequality constraints [that] arise
naturally in specifying many aspects of user interfaces, such as requiring that
one window be to the left of another ... or preferring that an object be
contained within a rectangle if possible", incrementally, via dual simplex
(Badros, Borning, Stuckey, ACM TOCHI,
https://constraints.cs.washington.edu/solvers/cassowary-tochi.pdf). Python has
it as kiwisolver: `solver.addConstraint((x1 == 40) | "weak")`, strengths
required/strong/medium/weak, and a `violated` check for non-required constraints
(https://kiwisolver.readthedocs.io/en/latest/basis/basic_systems.html).

**Apple Auto Layout** (Cassowary-based; **unverified** from an Apple primary
source here) writes each constraint as
`item1.attribute1 = multiplier × item2.attribute2 + constant`, with `=`, `>=`,
`<=`; priority 1..1000, 1000 required, and "unsatisfied optional constraints
act as a force pulling views towards them"
(https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/AutolayoutPG/AnatomyofaConstraint.html).
Errors are classed as "Unsatisfiable", "Ambiguous" (two or more solutions) and
"Logical" (https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/AutolayoutPG/TypesofErrors.html).
How each is reported is the instructive part:
- Unsatisfiable: the system "breaks one of the conflicting constraints ... until
  it finds a valid layout" and logs it; "the effect of breaking constraints can
  vary greatly from layout to layout, or even from build to build"
  (https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/AutolayoutPG/ConflictingLayouts.html).
- Ambiguous: "Auto Layout chooses one of the possible solutions ... there are no
  warnings written to the console, and there is no way to set a breakpoint for
  ambiguous layouts"; debug-only probes `hasAmbiguousLayout`,
  `exerciseAmbiguityInLayout`, `constraintsAffectingLayoutForAxis:`
  (https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/AutolayoutPG/AmbiguousLayouts.html).

**CSS** resolves over-constraint by rule, silently: if every term of the
horizontal box equation is set, "the specified value of 'margin-right' is
ignored and the value is calculated so as to make the equality true"
(CSS 2.1 §10.3.3, https://www.w3.org/TR/CSS21/visudet.html). Grid gives a
declarative, readable 2-D form: `grid-template-areas`, "Each string is a row,
and each word an area"; items "can overlap when they are positioned into
intersecting grid areas" (https://www.w3.org/TR/css-grid-1/).

**Lesson for pkidl.** Relative placement as linear constraints with strengths
is solved and available in Python (kiwisolver). The failure to copy is the
reporting: Auto Layout's silent pick for ambiguity and build-to-build variation
for conflicts, CSS's silent drop. pkidl must report under-constrained (which
parts are free, along which axis) and over-constrained (which named intents
conflict, at which source line) as results, with a deterministic tie-break.
Constraints need identities, which Auto Layout added as an afterthought.

## 7. Infrastructure as code: Terraform vs Pulumi

**Terraform**: declarative HCL; `plan` "Compares the current configuration to
the prior state and noting any differences" and "does not actually carry out
the proposed changes"; `-out` saves a plan that `apply` executes exactly;
`-detailed-exitcode` gives 0 no changes / 1 error / 2 changes; `-json` gives
"machine readable JSON UI output"
(https://developer.hashicorp.com/terraform/cli/commands/plan). HCL's own
rationale: a "compromise between generic serialization formats such as JSON and
configuration formats built around full programming languages", whose defined
structure "allows for better error messages", and with a JSON equivalent so
configuration can be "a mixture of human-authored configuration files in the
native syntax and machine-generated files in JSON"
(https://github.com/hashicorp/hcl). The general-purpose-language front end
for Terraform, CDK for Terraform, is archived (`gh api repos/hashicorp/terraform-cdk`
→ `"archived": true`, checked 2026-11-11).

**Pulumi**: general-purpose languages, but each resource constructor only
declares: "the language host has expressed that this bucket is part of the
desired state", then "the engine works with the resource provider to determine
what, if anything, has changed", and deletes what is no longer registered
(https://www.pulumi.com/docs/iac/concepts/how-pulumi-works/). Pulumi's own
comparison claims loops, abstraction, ordinary unit tests with a mocked engine,
IDE support, and that AI coding agents "have seen far more Python, TypeScript,
and Go than HCL"; HCL "constrains abstraction by design"
(https://www.pulumi.com/docs/iac/concepts/vs/terraform/; vendor claim).

**Lesson for pkidl.** Pulumi and Terraform agree on the part that matters: a
desired-state model, a diff against current state, and a reviewable plan before
apply. They differ only in the authoring surface. That is the charter's
"engines propose, the core applies", and it also answers how imperative-looking
Python can stay declarative: the script registers intent; it never mutates the
board.

## 8. Designing APIs for LLM agents (evidence, not opinion)

- **Code beats JSON as an action format.** CodeAct: executable Python actions
  "outperforms widely used alternatives (up to 20% higher success rate)" across
  17 LLMs (https://arxiv.org/abs/2402.01030).
- **Low-resource languages cost accuracy.** "Code LLMs produce impressive results
  on programming languages that are well represented in their training data
  ... but struggle with low-resource languages"
  (MultiPL-T, https://arxiv.org/abs/2308.09895). A new `.ato`-style syntax starts
  at zero training data.
- **Interface design moves agent success measurably.** SWE-agent ablations on
  SWE-bench Lite (GPT-4 Turbo, full config 18.0% resolved): edit without the
  linting guardrail 15.0, no edit command 10.3, full-file viewer instead of a
  100-line window 12.7, iterative instead of summarised search 12.0. Principles:
  "Environment feedback should be informative but concise"; "Guardrails mitigate
  error propagation and hasten recovery" (https://arxiv.org/html/2405.15793).
- **Names over opaque IDs; actionable errors; concise mode.** Anthropic,
  2025-09-11: agents "grapple with natural language names, terms, or identifiers
  significantly more successfully" than UUIDs; resolving UUIDs to readable names
  "significantly improves Claude's precision in retrieval tasks"; "prompt-engineer
  your error responses to clearly communicate specific and actionable
  improvements"; a `response_format` concise/detailed switch cut one example
  from 206 to 72 tokens (https://www.anthropic.com/engineering/writing-tools-for-agents).
- **Independent, numeric verification is the feedback that works.** ModelRift
  (section 2): 9 of 16 failures were never reported by the tool; numeric checks,
  not renders, caught the serious ones. CADTestBench: executable tests that
  "verify whether a generated CAD model satisfies the geometric and topological
  requirements" can also "guide CAD model generation"
  (https://arxiv.org/abs/2605.07807).

---

## Lessons for pkidl

1. **Values and operators, not an ambient context.** build123d left CadQuery's
   hidden stack, yet its builder mode's ambient context produces documented
   traps ("the move operation has no effect"). Amaranth removed domain
   propagation as "spooky action at a distance" (RFC 59). SKiDL's
   `default_circuit` broke packages (#86) and tooling (#168). → A `Board` is
   passed explicitly; placement is a value applied to an object (algebra-mode
   style), never "whatever `with` block is open". If a `with board:` sugar
   exists, it must only register into a named board and must return the object.

2. **The script builds an IR; output is a separate step.** Amaranth's
   elaborate-then-emit, Chisel's FIRRTL, Pulumi's register-then-diff, and
   SKiDL #168's request to split "compilation parameters" from circuit source
   all point the same way. → User code returns/populates an intent model;
   `build()` solves and emits; nothing touches a `.kicad_pcb` during user code.

3. **Plan before apply, as data.** Terraform `plan -out` / `-json` /
   `-detailed-exitcode`. → `pkidl plan` emits a structured change set (parts
   moved, tracks added, intents newly violated) that a person or agent reviews;
   `apply` takes exactly that plan. This is the charter's "engines propose".

4. **Report under- and over-constraint; never pick silently.** Auto Layout
   picks among ambiguous solutions with "no warnings", and conflict resolution
   varies "from build to build"; CSS drops `margin-right` silently. → Placement
   results say which parts are free on which axis and which named intents
   conflict, with a deterministic tie-break, and strength (required vs
   preferred) is explicit, as in kiwisolver.

5. **Every diagnostic carries the user's file:line and a name.** Amaranth's
   `src_loc` on every object, Chisel's naming plugin, Auto Layout's late
   `identifier`. → Each intent records where it was written and gets a stable
   name (from the variable or an explicit `name=`); errors cite both, plus the
   board objects in board terms.

6. **Catch the embedding's sharp edges at runtime.** Amaranth's `if m.If`
   SyntaxError with the fix in the message, and its "created but never used"
   warning at the construction site; SKiDL's dropped-reference problem, which
   drove atopile to its own language. → Warn on intents created but not attached
   to a board; turn known misuses into errors that name the correct form.

7. **Identity from the netlist, not from execution order.** SKiDL #238:
   auto-assigned refs move when code is reordered, breaking KiCad re-import;
   Chisel added a plugin for name stability. → Physical objects key on refdes /
   SKiDL tag / pin / net name; anything pkidl generates (vias, tracks, zones)
   gets IDs derived from the intent that made it, so reordering code changes no
   bytes.

8. **Selectors are typed Python with string sugar, over logical identity.**
   build123d replaced CadQuery's string selectors with Python filters for IDE
   support; geometric selection is fragile in both. → `on_net("GND")`,
   `where(value="100nF")` as typed query objects; `"C1..C4"` parses into the
   same object and a bad string fails with the parse position.

9. **Blocks: elaborate once, place per instance, query into instances.**
   Chisel `Definition`/`Instance`/`@public`; SKiDL's subcircuit composability
   problem (#48) came from adding `Circuit` late. → A layout block is a value
   with typed ports, defined once and instantiated per subcircuit instance,
   designed in from the first board files (charter step 4).

10. **Verification is independent and numeric; renders are secondary.**
    ModelRift: 9/16 failures unreported by the tool, both tools certified broken
    output, renders caught only coarse blunders. → Layer 4 (measure each intent
    on the real result) is the agent's primary feedback; the render helps people
    and catches gross errors.

11. **Agent-facing output: names, concise by default, structured.** Anthropic's
    tool guidance (names over UUIDs, actionable errors, concise mode) and
    SWE-agent (concise feedback and guardrails worth several points). → KiCad
    UUIDs never appear without the refdes/net; diagnostics have a JSON form and
    a short form; an explicit "no violations" line rather than empty output.

12. **Keep source locations out of the emitted board.** Chisel ships
    `--no-source-info` because locators in output fight stable output. → src
    locations live in diagnostics and an optional sidecar, not in the
    `.kicad_pcb`, so determinism holds.

## Recommendation on the open question

**Both over one model, with Python as the authoring language and a typed,
serialisable intent model as the thing everything else reads.** Concretely:

- **Author in Python, not in a new language.** Agents do better writing code
  than JSON (CodeAct, up to 20%) and worse in low-resource languages
  (MultiPL-T); a new syntax starts with no training data and a parser to
  maintain (atopile is still on ANTLR, "pending bespoke lexer/parser"). Python
  also supplies loops, functions and tests that HCL "constrains ... by design"
  (Pulumi). atopile's arguments for a language, dropped references and
  imperative scripts, are answered inside Python by Amaranth's must-use warning
  and by an IR the script only builds.
- **But the Python must be declarative in effect**, as Pulumi's is: calls
  register intent in an explicit model; solvers and KiCad emission run after.
  This is the charter's "calls that read imperatively build inspectable
  constraints underneath", and the evidence supports it.
- **Make the intent model itself a first-class, canonical data form** (one
  schema, deterministic JSON/YAML serialisation) for three uses the evidence
  names: the plan/diff an agent and reviewer read (Terraform), the target of
  machine-generated or machine-edited intent (HCL's "mixture of human-authored
  ... and machine-generated files in JSON"; atopile's ato and fabll over one
  type-graph), and the structured diagnostics (Anthropic, SWE-agent). Do not
  ask humans to author it.
- **Defer data-as-input.** Whether an agent should *edit* the data form rather
  than the Python is not settled by this evidence: CodeAct says code, HCL's JSON
  path says data for generated parts. Step 4 decides it cheaply: write 2-3 corpus
  boards in Python, dump the model, and have an agent make the same revision
  both ways; keep data-as-input only if it wins. Until then, keep the model
  round-trippable so that option stays open.

## Charter principles the evidence contradicts or qualifies

- **"Explicit objects, no hidden state ... (CadQuery's lesson)"** holds, but the
  model to copy is build123d's *algebra* mode. Its builder mode (the one its
  introduction uses to contrast with CadQuery) is itself ambient state with
  documented traps.
  Citing build123d without that distinction invites `with Board():` sugar
  that reintroduces SKiDL's problem.
- **"Seeing is part of the loop. A render after every build, for people and for
  agents"**: ModelRift found renders caught only coarse blunders; numeric checks
  caught the defects that mattered. The render is useful, but the agent's loop
  should rest on layer-4 measurements; the principle should not read as if the
  render were the agent's eyes.
- **"Selectors: `"C1..C4"` ..."**: string selectors are what build123d removed.
  Keep the string as sugar over typed selector objects, not as the primitive.
- **"Determinism. The same input gives the same bytes"** is compatible, but
  only if source locations and creation order never leak into output (Chisel's
  `--no-source-info`, SKiDL #238). The charter should say identity comes from
  the netlist and intent, not from execution order.
- Missing from the principles, and supported by every constraint system here:
  **under- and over-constrained placement is a reported result, never a silent
  choice.** "Results, not booleans" covers routing only; it should cover
  placement and every solver.
