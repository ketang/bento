---
name: quality-standards
description: Concrete thresholds and named code smell catalog for the code quality audit phase
---

# Quality Standards

This reference is loaded during audit generation to govern the **code quality**
audit phase. Apply thresholds as pass/fail criteria. Apply code smells as named
patterns to look for when reading sampled files.

## Concrete Thresholds

| Dimension | Warning | Error |
|---|---|---|
| Function length (excl. blank lines and comments) | > 25 lines | > 50 lines |
| File length | > 300 lines | > 600 lines |
| Function parameters | > 4 | > 7 |
| Nesting depth | > 3 levels | > 5 levels |
| Cyclomatic complexity | > 10 per function | > 20 per function |
| Cognitive complexity | > 15 per function | — |
| Return points | > 3 per function | — |
| Public API doc coverage | any exported symbol missing a doc comment | — |

## Named Code Smells

Each finding is reported with: file path, line number (if applicable), smell
name, and a one-sentence explanation of why it applies here.

### Structural Smells

**God object** — one type or file owns disproportionate responsibility. Diagnostic:
ask "what does this not do?" If the answer is short, it is a god object.

**Anemic domain model** — domain types are pure data bags; all business logic
lives in external manager, service, or util layers. Diagnostic: can you add
behaviour to this type without touching anything else?

**Middle man** — a module or type exists solely to delegate every call to
another; it provides no logic of its own. Diagnostic: if you deleted this layer
and called the downstream directly, would anything break?

**Refused bequest** — a subtype overrides or ignores most of what it inherits,
suggesting the inheritance hierarchy models the wrong relationship.

**Inappropriate intimacy** — two modules reference each other's internals
bidirectionally; neither has a clean boundary. Diagnostic: can either module be
understood without reading the other?

### Coupling Smells

**Feature envy** — a function spends more time operating on another module's
data than its own. Diagnostic: which module does this function belong in, by the
data it touches?

**Message chains** — callers traverse deep chains of internal structure
(`a.b().c().d()`), coupling themselves to implementation details at every level.

**Temporal coupling** — a caller must invoke methods in a specific undocumented
order for correct behaviour. Look for: unguarded `Init`, `Open`, `Start`, or
`Connect` methods with no state guard; doc comments that say "must call X before
Y"; nil or zero-value reads that can only be safe after a specific prior call.

**Hidden side effects** — a function that reads or queries by name but also
mutates state or triggers I/O.

### Data Smells

**Data clump** — three or more values that always appear together (passed as
parameters, stored together, returned together) but are never structured into a
named type.

**Primitive obsession** — domain concepts expressed as raw strings, integers, or
booleans instead of typed values (e.g. a user role stored as `string` rather
than a `Role` type).

**Stringly typed** — config, errors, or events passed as unvalidated raw strings
where types would eliminate entire classes of error at compile or lint time.

**Magic values** — unexplained literals embedded in logic with no named constant
or explanatory comment.

### Design Smells

**Divergent change** — a module changes for multiple unrelated reasons, revealing
low cohesion.

**Leaky abstraction** — callers must know implementation details to use a
component correctly. Diagnostic: can a caller be written from the interface
alone, or must they read the implementation?

**Inconsistent abstraction level** — a function mixes high-level intent (what it
is doing) with low-level implementation detail (how) in the same body, making it
harder to read at either level.

## Design-Level Heuristics

For each unit sampled during the code quality phase, assess:

- Can you explain what this unit does in one sentence without mentioning its
  internals?
- Can you change the internals without breaking callers?
- Does naming match the domain vocabulary, or is it generic (`Manager`,
  `Handler`, `Data`, `Info`, `Util`)?
- Is error handling deliberate — typed errors, context added at the right layer
  — or reflexive (`if err != nil { return err }`)?
- Are interfaces discovered (extracted from real usage across callers) or
  invented (speculative, with one implementation)?

## Severity Model

All findings — from static analysis tools and from model code review — use this
scale:

| Level | Meaning |
|---|---|
| `error` | Must fix before merge or release |
| `warning` | Should fix before the next feature cycle |
| `note` | Worth addressing; not urgent |
| `skip` | Acknowledged, intentionally deferred |

## Sampling Strategy

Apply the code quality phase in this priority order:

1. Files from `risk_surfaces` in the discovery output (auth, routers, persistence,
   external network, background jobs, secrets handling)
2. Highest-churn files: `git log --format='' --name-only | sort | uniq -c | sort -rn | head -20`
3. Remaining files until a representative sample is reached

Report by file. Stop when the pattern is clear — exhaustive coverage of every
file is not the goal.
