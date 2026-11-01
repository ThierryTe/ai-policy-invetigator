These four workflow definitions were archived after local validation of the replacement
CI/CD pipeline. GitHub Actions does not load this directory. Recovery scripts and the
successful V8 release `r041243000818-11` remain untouched.

Use [the current deployment guide](../../docs/PRODUCTION_PIPELINE.md) for routine delivery.
Do not restore the old workflows as part of ordinary deployment or worker activation.
Historical regression tests read these copies to preserve recovery tooling coverage.
