"""Create the third-party license bundle included in Windows builds.

The PyInstaller application contains Python packages frozen from the active build
environment.  This tool copies every installed distribution's declared license
files (not just the direct application dependencies) so the release bundle does
not silently omit licenses for transitive or PyInstaller-collected packages.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from importlib.metadata import Distribution, distributions
from pathlib import Path

PROJECT_DISTRIBUTION = "pgn-extractor-gui"
LICENSE_FILE_PATTERN = re.compile(r"^(?:copying|licen[cs]e|notice)(?:[._-].*)?$", re.IGNORECASE)
NATIVE_NOTICE_FILENAMES = (
    "NATIVE_RUNTIME_COMPONENTS.md",
    "dotnet-runtime-MIT-LICENSE.txt",
    "microsoft-webview2-1.0.3856.49-LICENSE.txt",
    "microsoft-webview2-1.0.3856.49-NOTICE.txt",
)


def normalized_name(name: str) -> str:
    """Return a stable, filesystem-safe name for a Python distribution."""

    return re.sub(r"[^A-Za-z0-9.-]+", "-", name).strip("-").lower()


def distribution_name(distribution: Distribution) -> str:
    name = distribution.metadata.get("Name")
    if not name:
        raise ValueError("Installed distribution metadata is missing Name.")
    return name


def declared_license_filenames(distribution: Distribution) -> set[str]:
    """Return license-file names explicitly declared by package metadata."""

    return {
        Path(value.replace("\\", "/")).name.lower()
        for value in distribution.metadata.get_all("License-File") or []
    }


def is_license_file(relative_path: str, declared_names: set[str]) -> bool:
    """Identify a license/notice file recorded by wheel metadata."""

    parts = relative_path.replace("\\", "/").split("/")
    filename = parts[-1]
    return LICENSE_FILE_PATTERN.match(filename) is not None or filename.lower() in declared_names


def license_files(distribution: Distribution) -> list[Path]:
    """Return declared, existing license files for one installed distribution."""

    files: list[Path] = []
    declared_names = declared_license_filenames(distribution)
    for file in distribution.files or ():
        if not is_license_file(str(file), declared_names):
            continue
        candidate = Path(distribution.locate_file(file))
        if candidate.is_file():
            files.append(candidate)
    return sorted(set(files), key=lambda path: str(path).lower())


def metadata_license(distribution: Distribution) -> str:
    """Return the most specific license field supplied by package metadata."""

    expression = distribution.metadata.get("License-Expression")
    if expression:
        return expression
    license_name = distribution.metadata.get("License")
    if normalized_name(distribution_name(distribution)) == "proxy-tools":
        return "BSD (source header; installed metadata reports MIT)"
    if not license_name:
        return "Not declared in installed metadata"
    collapsed = " ".join(license_name.split())
    return collapsed if len(collapsed) <= 120 else "See bundled license file"


def source_url(distribution: Distribution) -> str:
    """Return a project/source URL when metadata provides one."""

    project_urls = distribution.metadata.get_all("Project-URL") or []
    for project_url in project_urls:
        if "," in project_url:
            label, url = project_url.split(",", 1)
            if label.strip().lower() in {"source", "sources", "repository"}:
                return url.strip()
    return distribution.metadata.get("Home-page", "")


def copy_license_files(source_files: list[Path], destination: Path) -> list[str]:
    """Copy license files to one package-specific directory without collisions."""

    copied: list[str] = []
    for index, source in enumerate(source_files, start=1):
        target_name = source.name
        target = destination / target_name
        if target.exists():
            target = destination / f"{index}-{target_name}"
        shutil.copyfile(source, target)
        copied.append(target.name)
    return copied


def prepare_output_directory(output_dir: Path) -> None:
    """Replace only the generated directory requested by the caller."""

    resolved = output_dir.resolve()
    if resolved == resolved.anchor or not resolved.name:
        raise ValueError("Refusing to use a filesystem root as the license output directory.")
    if output_dir.exists():
        if output_dir.is_symlink():
            raise ValueError("Refusing to replace a symbolic-link license output directory.")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)


def copy_native_runtime_notices(output_dir: Path, overrides_dir: Path) -> list[str]:
    """Copy checked-in notices for non-Python runtime components."""

    destination = output_dir / "native-runtime"
    destination.mkdir()
    copied: list[str] = []
    for filename in NATIVE_NOTICE_FILENAMES:
        source = overrides_dir / filename
        if not source.is_file():
            raise ValueError(f"Required native runtime notice is missing: {filename}.")
        shutil.copyfile(source, destination / filename)
        copied.append(filename)
    return copied


def collect(output_dir: Path, overrides_dir: Path) -> int:
    """Collect license files and return the number of Python distributions covered."""

    prepare_output_directory(output_dir)
    rows = [
        "This directory is generated by tools/collect_third_party_licenses.py.",
        "It contains license material for every installed Python distribution in the",
        "Windows build environment, excluding this application itself. Extra build-only",
        "notices may be present intentionally; do not remove them from a release.",
        "",
        "Component\tVersion\tMetadata license\tSource/home page\tBundled files",
    ]

    discovered = sorted(distributions(), key=lambda item: normalized_name(distribution_name(item)))
    seen: set[tuple[str, str]] = set()
    for distribution in discovered:
        name = distribution_name(distribution)
        version = distribution.version
        identity = (normalized_name(name), version)
        if identity in seen or normalized_name(name) == PROJECT_DISTRIBUTION:
            continue
        seen.add(identity)

        component_dir = output_dir / f"{normalized_name(name)}-{version}"
        component_dir.mkdir()
        files = license_files(distribution)
        if not files:
            override = overrides_dir / f"{normalized_name(name)}-LICENSE.txt"
            if override.is_file():
                files = [override]
            else:
                raise ValueError(
                    f"No license file was found for {name} {version}. "
                    f"Add a checked-in override at {override.name}."
                )

        copied = copy_license_files(files, component_dir)
        rows.append(
            "\t".join(
                (
                    name,
                    version,
                    metadata_license(distribution),
                    source_url(distribution),
                    ", ".join(copied),
                )
            )
        )

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise ValueError("The active Python runtime does not provide LICENSE.txt.")
    python_version = ".".join(str(part) for part in sys.version_info[:3])
    python_destination = output_dir / f"python-{python_version}"
    python_destination.mkdir()
    shutil.copyfile(python_license, python_destination / "LICENSE.txt")
    rows.append(
        f"Python\t{python_version}\tPSF-2.0 and bundled component notices\t"
        "https://www.python.org/psf/license/\tLICENSE.txt"
    )
    native_notices = copy_native_runtime_notices(output_dir, overrides_dir)
    rows.extend(
        (
            (
                "Microsoft.Web.WebView2 SDK\t1.0.3856.49\tBSD-3-Clause-style terms\t"
                "https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.3856.49\t"
                f"native-runtime/{native_notices[2]}, native-runtime/{native_notices[3]}"
            ),
            (
                ".NET assemblies bundled by pythonnet\twith pythonnet 3.1.0\tMIT\t"
                "https://github.com/dotnet/runtime/blob/main/LICENSE.TXT\t"
                f"native-runtime/{native_notices[0]}, native-runtime/{native_notices[1]}"
            ),
        )
    )

    (output_dir / "MANIFEST.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return len(seen)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect third-party license files for a release.")
    parser.add_argument("output_dir", type=Path, help="Generated license directory to replace.")
    parser.add_argument(
        "--overrides-dir",
        type=Path,
        default=Path(__file__).with_name("license_overrides"),
        help="Checked-in license files used only when installed metadata lacks one.",
    )
    args = parser.parse_args()

    try:
        distribution_count = collect(args.output_dir, args.overrides_dir)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1

    print(f"Collected third-party license material for {distribution_count} Python distributions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
