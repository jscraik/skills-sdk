"""Print a portable candidate identity without touching external state."""

from skills_sdk.models.package import PackageCandidateIdentity


def main() -> None:
    candidate = PackageCandidateIdentity(
        package_id="example-skill",
        source_revision="0" * 40,
        content_sha256="0" * 64,
    )
    print(candidate.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
