# mIA - Project Instructions

## Objective

mIA is a modular enterprise AI platform.

The project must prioritize:

1. Correctness and preservation of existing functionality.
2. Response time and runtime performance.
3. Clean modular architecture.
4. Maintainability.
5. Regression prevention.
6. Future extensibility.
7. Separation between conversational AI, business domains and predictive systems.

Before modifying code, investigate the relevant implementation completely.

Never speculate about code that has not been inspected.

---

# Architecture principles

The architecture must be modular.

Avoid:

- monolithic files
- duplicate business logic
- unnecessary wrappers
- unnecessary compatibility layers
- hidden fallbacks
- duplicated routes
- dead code
- circular dependencies
- implicit dependencies between domains

Prefer:

- small focused modules
- explicit contracts
- reusable services
- clear domain boundaries
- dependency injection where useful
- observable execution paths
- deterministic routing

Performance and response times are first-class requirements.

Do not introduce abstractions that make execution slower without a justified architectural benefit.

---

# Legacy policy

MIA Backend Legacy is READ-ONLY reference material.

NEVER modify it.

New functionality must not depend on it.

Do not create:

- imports from legacy
- runtime fallbacks to legacy
- compatibility wrappers for legacy
- duplicated legacy code
- references to legacy architecture in new modules

The final architecture must be capable of operating after the legacy implementation is completely removed.

Legacy may only be inspected to determine previous behaviour or to verify that functionality has not been lost.

---

# Version naming

New architecture and new functionality must not introduce internal architecture names such as:

- legacy
- v11
- v12
- v13
- vX
- version-based compatibility modules

Names must describe responsibility or domain instead of historical versions.

---

# Existing functional areas

The system contains several functional domains, including:

- conversational chat
- mail
- voice
- business data access
- frontend integration
- 2D avatar
- 3D avatar
- future holographic frontend

Changes in one domain must not silently break another.

---

# Mail

Mail functionality must preserve conversational queries.

Examples of expected behaviour include natural requests such as:

- summarize my latest emails
- summarize the last 10 emails
- show recent inbox messages
- find emails about a subject
- summarize a conversation

Do not optimize only for exact phrases.

Intent detection must tolerate natural language variation.

---

# Conversational behaviour

mIA is a conversational assistant.

Functionality must not depend exclusively on exact commands or rigid wording.

When modifying:

- intent routing
- semantic parsing
- tool selection
- domain dispatch
- context handling
- response generation

verify that alternative natural-language formulations continue to work.

Do not consider a feature complete only because one canonical prompt passes.

---

# Regression policy

Before declaring a change complete:

1. Identify affected capabilities.
2. Identify existing regression risks.
3. Run existing tests.
4. Add tests when behaviour is not covered.
5. Test several natural-language formulations when conversational behaviour is affected.
6. Verify Backend behaviour.
7. Verify Gateway behaviour when affected.
8. Verify frontend contract when affected.

A successful isolated unit test does not prove that the complete conversational flow works.

---

# Predictive architecture

The project must contain a predictive subsystem structurally separated from the LLM and transactional business domains.

It must be designed to support progressively:

- feature definitions
- datasets
- snapshots
- training
- scoring
- forecasting
- explainability
- model registry
- evaluation
- monitoring

Do not couple predictive logic directly to the conversational LLM layer.

The predictive module may initially contain infrastructure and contracts without trained business models.

---

# Holographic frontend

The architecture must remain compatible with a future holographic frontend.

The reserved HG frontend area must remain logically separated from the existing 2D/3D implementation.

Backend business logic must not depend on a specific avatar renderer.

---

# Change procedure

For non-trivial changes:

PHASE 1 - INVESTIGATE

Inspect:

- entry points
- dependencies
- callers
- callees
- tests
- configuration
- domain contracts
- frontend/backend contracts

PHASE 2 - PLAN

Explain:

- root cause
- affected files
- proposed changes
- risks
- regression surface
- tests to execute

Do not modify files during this phase.

PHASE 3 - IMPLEMENT

Make the smallest coherent architectural change.

Do not add temporary compatibility code unless explicitly requested.

PHASE 4 - VALIDATE

Run relevant tests and inspect their results.

PHASE 5 - REPORT

Report:

- files modified
- behaviour changed
- tests executed
- test results
- remaining risks

Never report a module as complete if relevant tests are failing.

---

# Git

Never push changes to a remote repository without explicit user approval.

Never perform destructive Git operations such as:

git reset --hard
git clean -fd
git clean -xdf

without explicit user direction.

Inspect git diff before considering a task complete.

Do not revert unrelated user changes.

---

# Secrets

Never expose, print, commit or copy:

- passwords
- API keys
- access tokens
- refresh tokens
- private certificates
- authentication cookies
- client secrets

Use environment variables or existing secure configuration mechanisms.

Do not replace real secret values with new hardcoded values.

---

# General working rule

Investigate before answering.

If the user references functionality, locate its actual implementation before making claims about how it works.

Prefer evidence from the repository over assumptions.