# Project Collaboration Rules

## Learning mode

- This repository is both a recruiting project and a guided learning project.
- Default to explaining the concept, assigning a bounded task, and reviewing the learner's implementation.
- Do not replace a learning task with a complete generated implementation unless the user explicitly requests it.
- Keep changes small enough to explain in an interview.

## Progress tracking

- The canonical roadmap is `../PROGRESS.md`.
- The daily learning record is `../LEARNING_LOG.md`.
- Mark a milestone complete only after its code exists, tests pass, and the learner can explain the design.
- Record the commit hash or test evidence in the roadmap after verification.
- Treat roadmap dates as planning guidance. Advance immediately after mastery checks pass, and split tasks when they do not.
- Do not slow the learner down to match calendar dates, and do not skip foundational acceptance criteria to move faster.

## Engineering standards

- Use Python 3.11 or newer and keep the `src` package layout.
- Add or update tests with every behavior change.
- Prefer typed boundaries with Pydantic models.
- Never invent benchmark results or resume metrics.
- Keep the project focused on auditable retail analytics; do not add unrelated framework demos.
