# Reviewed frontend Compose contract for backend CI

Source: https://github.com/ThierryTe/ai-policy-investigator-frontend

Imported path: `compose.yaml` only, from the inspected develop working copy.
Frontend commit context: `25e494a76f234bfcb56c769fe0b92817d594eee6` (worktree bytes are recorded below).
SHA-256: `e935033c410d85c08198ace352e548995688390cfb2411fc6fdd9b2c47916f23`.

This is configuration-only test material, not a frontend build or Git history import.
It allows the existing production verifier and all Python tests to run without
private cross-repository credentials. The source repository was not publicly readable
at preparation time. Local tests compare this snapshot with the selected actual
frontend checkout; changes to the frontend Compose contract require deliberate review
and a snapshot/hash update. CI cannot automatically detect independent future changes
in a private frontend repository. Do not use this fixture to build/deploy the frontend.
