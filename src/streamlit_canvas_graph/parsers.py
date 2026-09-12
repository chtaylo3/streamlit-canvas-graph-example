from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import PurePosixPath


@dataclass(slots=True)
class PackageDependency:
    name: str
    specifier: str = ""
    relationship: str = "dependency"
    target_location: str | None = None
    optional: bool = False


@dataclass(slots=True)
class Package:
    name: str
    version: str
    ecosystem: str
    direct: bool = False
    dependencies: list[PackageDependency] = field(default_factory=list)
    location: str | None = None
    direct_relationships: tuple[str, ...] = ()
    direct_optional: bool = False


@dataclass(slots=True)
class ParsedManifest:
    path: str
    ecosystem: str
    parser: str
    packages: list[Package]
    complete: bool = True
    warnings: list[str] = field(default_factory=list)


def parse_manifest(path: str, content: str) -> ParsedManifest:
    name = PurePosixPath(path).name
    if name in {"package-lock.json", "npm-shrinkwrap.json"}:
        return parse_package_lock(path, content)
    if name == "uv.lock" or name == "poetry.lock":
        return parse_python_lock(path, content, name.removesuffix(".lock"))
    if name.startswith("requirements") and name.endswith(".txt"):
        return parse_requirements(path, content)
    if name == "packages.lock.json":
        return parse_nuget_lock(path, content)
    if name == "Directory.Packages.props" or name.endswith(
        (".csproj", ".fsproj", ".vbproj")
    ):
        return parse_nuget_xml(path, content)
    if name in {"yarn.lock", "pnpm-lock.yaml"}:
        return ParsedManifest(
            path,
            "npm",
            name,
            [],
            False,
            [
                f"{name} is recorded but requires SBOM relationships for complete resolution"
            ],
        )
    raise ValueError(f"Unsupported manifest: {path}")


def parse_package_lock(path: str, content: str) -> ParsedManifest:
    payload = json.loads(content)
    packages: list[Package] = []
    entries = payload.get("packages", {})
    root = entries.get("", {})
    root_relationships: dict[str, set[str]] = {}
    for group, relationship in (
        ("dependencies", "dependency"),
        ("devDependencies", "dev"),
        ("optionalDependencies", "optional"),
        ("peerDependencies", "peer"),
    ):
        for name in root.get(group, {}):
            root_relationships.setdefault(name, set()).add(relationship)
    optional_root_peers = {
        name
        for name, metadata in root.get("peerDependenciesMeta", {}).items()
        if isinstance(metadata, dict) and metadata.get("optional")
    }
    # Root peerDependencies describe host compatibility rather than ownership,
    # so they are retained as peer relationships instead of ordinary dependencies.
    # The top-level `dependencies` tree is lockfile-v1 compatibility data in
    # modern lockfiles and must not be used when the authoritative root package
    # entry exists.
    install_records = {
        location: record
        for location, record in entries.items()
        if location and isinstance(record, dict) and "version" in record
    }
    install_targets = {location: location for location in install_records}
    for location, record in entries.items():
        if not location or not isinstance(record, dict) or not record.get("link"):
            continue
        resolved = str(record.get("resolved", "")).removeprefix("./")
        if resolved in install_records:
            install_targets[location] = resolved
    direct_by_location: dict[str, set[str]] = {}
    for name, relationships in root_relationships.items():
        direct_location = install_targets.get(f"node_modules/{name}")
        if direct_location:
            direct_by_location.setdefault(direct_location, set()).update(relationships)
    for location, record in install_records.items():
        if not location or "version" not in record:
            continue
        name = record.get("name") or location.rsplit("node_modules/", 1)[-1]
        dependencies: list[PackageDependency] = []
        ordinary = dict(record.get("dependencies", {}))
        optional = dict(record.get("optionalDependencies", {}))
        # npm treats an optional declaration as overriding an ordinary declaration
        # of the same name. Preserve one correctly typed relationship.
        for dep_name in optional:
            ordinary.pop(dep_name, None)
        for dep_name, spec in ordinary.items():
            dependencies.append(
                PackageDependency(
                    dep_name,
                    str(spec),
                    target_location=_resolve_npm_target(
                        install_targets, location, dep_name
                    ),
                )
            )
        for dep_name, spec in optional.items():
            dependencies.append(
                PackageDependency(
                    dep_name,
                    str(spec),
                    relationship="optional",
                    target_location=_resolve_npm_target(
                        install_targets, location, dep_name
                    ),
                    optional=True,
                )
            )
        peer_metadata = record.get("peerDependenciesMeta", {})
        for dep_name, spec in record.get("peerDependencies", {}).items():
            is_optional = bool(peer_metadata.get(dep_name, {}).get("optional"))
            dependencies.append(
                PackageDependency(
                    dep_name,
                    str(spec),
                    relationship="peer",
                    target_location=_resolve_npm_target(
                        install_targets, location, dep_name
                    ),
                    optional=is_optional,
                )
            )
        direct_relationships = tuple(sorted(direct_by_location.get(location, set())))
        packages.append(
            Package(
                name,
                str(record["version"]),
                "npm",
                bool(direct_relationships),
                dependencies,
                location,
                direct_relationships,
                name in optional_root_peers and "peer" in direct_relationships,
            )
        )
    if not packages:
        packages.extend(_parse_legacy_npm_dependencies(payload.get("dependencies", {})))
    return ParsedManifest(
        path,
        "npm",
        "package-lock",
        packages,
        bool(packages),
        [] if packages else ["No resolved packages found"],
    )


def _resolve_npm_target(
    install_targets: dict[str, str],
    source_location: str,
    dependency_name: str,
) -> str | None:
    """Resolve an installed child using Node's nearest-node_modules lookup."""
    current = PurePosixPath(source_location)
    while True:
        candidate = (current / "node_modules" / dependency_name).as_posix()
        if candidate in install_targets:
            return install_targets[candidate]
        if current == PurePosixPath("."):
            return None
        current = current.parent


def _parse_legacy_npm_dependencies(
    dependencies: object,
    *,
    parent_location: str = "",
    direct: bool = True,
) -> list[Package]:
    """Flatten the nested package-lock v1 dependency tree with locations intact."""
    if not isinstance(dependencies, dict):
        return []
    packages: list[Package] = []
    for name, raw_record in dependencies.items():
        if not isinstance(raw_record, dict) or not raw_record.get("version"):
            continue
        location = "/".join(
            part for part in (parent_location, "node_modules", name) if part
        )
        children = raw_record.get("dependencies", {})
        child_packages = _parse_legacy_npm_dependencies(
            children, parent_location=location, direct=False
        )
        child_locations = {
            package.name: package.location
            for package in child_packages
            if package.location == f"{location}/node_modules/{package.name}"
        }
        packages.append(
            Package(
                name,
                str(raw_record["version"]),
                "npm",
                direct,
                [
                    PackageDependency(
                        child_name,
                        str(child_record.get("version", ""))
                        if isinstance(child_record, dict)
                        else "",
                        target_location=child_locations.get(child_name),
                    )
                    for child_name, child_record in children.items()
                ]
                if isinstance(children, dict)
                else [],
                location,
                ("dependency",) if direct else (),
            )
        )
        packages.extend(child_packages)
    return packages


def parse_python_lock(path: str, content: str, parser: str) -> ParsedManifest:
    payload = tomllib.loads(content)
    records = payload.get("package", [])
    local_records = {
        record.get("name"): record
        for record in records
        if record.get("name")
        and isinstance(record.get("source"), dict)
        and ({"editable", "virtual"} & record["source"].keys())
    }
    direct_names: set[str] = set()
    pending = [
        dependency.get("name")
        for record in local_records.values()
        for dependency in record.get("dependencies", [])
        if isinstance(dependency, dict) and dependency.get("name")
    ]
    seen_local: set[str] = set()
    while pending:
        name = pending.pop()
        if name in local_records:
            if name in seen_local:
                continue
            seen_local.add(name)
            pending.extend(
                dependency.get("name")
                for dependency in local_records[name].get("dependencies", [])
                if isinstance(dependency, dict) and dependency.get("name")
            )
        else:
            direct_names.add(name)
    packages: list[Package] = []
    for record in records:
        name, version = record.get("name"), record.get("version")
        if not name or not version or name in local_records:
            continue
        dependencies: list[PackageDependency] = []
        for dependency in record.get("dependencies", []):
            if isinstance(dependency, str):
                dependencies.append(PackageDependency(dependency))
            elif isinstance(dependency, dict) and dependency.get("name"):
                dependencies.append(
                    PackageDependency(
                        dependency["name"], str(dependency.get("version", ""))
                    )
                )
        packages.append(
            Package(
                name,
                str(version),
                "PyPI",
                name in direct_names,
                dependencies,
            )
        )
    return ParsedManifest(
        path,
        "PyPI",
        parser,
        packages,
        bool(packages),
        [] if packages else ["No resolved packages found"],
    )


REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9_.-]+)(?:\[[^]]+\])?\s*==\s*([^;\s]+)")


def parse_requirements(path: str, content: str) -> ParsedManifest:
    packages = [
        Package(match.group(1), match.group(2), "PyPI", True)
        for line in content.splitlines()
        if (match := REQUIREMENT.match(line))
    ]
    return ParsedManifest(
        path,
        "PyPI",
        "requirements",
        packages,
        False,
        ["requirements files do not encode parent-child relationships"],
    )


def parse_nuget_lock(path: str, content: str) -> ParsedManifest:
    payload = json.loads(content)
    merged: dict[tuple[str, str], Package] = {}
    for framework in payload.get("dependencies", {}).values():
        for name, record in framework.items():
            if not isinstance(record, dict):
                continue
            version = str(
                record.get("resolved") or record.get("requested") or ""
            ).strip("[]() ")
            if not version:
                continue
            key = (name.casefold(), version)
            dependencies = [
                PackageDependency(dep_name, str(spec).strip("[]() "))
                for dep_name, spec in record.get("dependencies", {}).items()
            ]
            merged[key] = Package(
                name,
                version,
                "NuGet",
                record.get("type") in {"Direct", "Project"},
                dependencies,
            )
    packages = list(merged.values())
    return ParsedManifest(
        path,
        "NuGet",
        "packages-lock",
        packages,
        bool(packages),
        [] if packages else ["No resolved packages found"],
    )


def parse_nuget_xml(path: str, content: str) -> ParsedManifest:
    root = ET.fromstring(content)
    packages: list[Package] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag not in {"PackageReference", "PackageVersion"}:
            continue
        name = element.attrib.get("Include") or element.attrib.get("Update")
        version = element.attrib.get("Version") or element.findtext("Version")
        if name and version and not version.startswith("$("):
            packages.append(Package(name, version, "NuGet", True))
    return ParsedManifest(
        path,
        "NuGet",
        "msbuild",
        packages,
        False,
        [
            "MSBuild manifests contain direct requirements; use lockfile or SBOM for transitives"
        ],
    )
