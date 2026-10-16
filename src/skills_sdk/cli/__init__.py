"""Command-line entry point for Skills SDK."""

COMMAND_HELP = {
    "inventory": "discovery-only: reserved source-inventory boundary (exits 3)",
    "intake": "run read-only package intake and normalization",
    "check-local": "run read-only intake and candidate-bound local checks",
    "validate": "run package contract validation",
    "build": "build an immutable package candidate",
    "eval": "run candidate-bound evaluation lanes",
    "package": "discovery-only: reserved package-preparation boundary (exits 3)",
    "project": "discovery-only: reserved runtime-projection boundary (exits 3)",
    "verify": "verify candidate-bound evidence",
}
