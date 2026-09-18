# Nadree API Implementation

- This directory is the implementation root for the independent Nadree rental backend, using Python and FastAPI with the existing shared database.
- Keep all new service code, tests, executable migrations, implementation notes, configuration templates, and deployment assets here. Do not place them in ../../RiderLog.
- Read README.md, ../rental-project-master.md, and ../rental-api-review-decisions.md before implementation. The parent API spreadsheet remains the contract source of truth; do not duplicate planning documents here.
- Existing RiderLog code and OpenAPI are reference material, not proof that this separate server already implements those endpoints or shares authentication automatically.
- Preserve shared database contracts. Coordinate migrations and cross-server transaction/locking rules. Never run the visualization SQL or automatic schema creation against the shared database.
- Do not write production data or execute production migrations without explicit approval. Use isolated test data and verify compatibility with the existing service.
- Do not copy secrets into source, documentation, logs, or example configuration. Keep service configuration and deployment independent.
- Keep changes scoped to approved requirements, update affected parent specifications, and distinguish planned, implemented, and tested states.
- Do not scaffold unused infrastructure or choose unneeded dependencies. Add code and directories as their work begins.
- This directory instruction does not grant filesystem permissions; request approval when the sandbox requires it.
