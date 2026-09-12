import json

from streamlit_canvas_graph.ingestion import classify_update
from streamlit_canvas_graph.parsers import parse_manifest


def test_package_lock_parses_direct_and_transitive_packages() -> None:
    payload = {
        "lockfileVersion": 2,
        "dependencies": {
            "alpha": {"version": "1.2.0"},
            "beta": {"version": "2.0.1"},
            "platform-binary": {"version": "3.0.0"},
        },
        "packages": {
            "": {
                "dependencies": {"alpha": "^1"},
                "devDependencies": {"test-helper": "^4"},
                "optionalDependencies": {"optional-helper": "^5"},
                "peerDependencies": {"host-library": "^6"},
            },
            "node_modules/alpha": {
                "name": "alpha",
                "version": "1.2.0",
                "dependencies": {"beta": "^2"},
            },
            "node_modules/parent/node_modules/alpha": {
                "name": "alpha",
                "version": "1.1.0",
            },
            "node_modules/beta": {"name": "beta", "version": "2.0.1"},
            "node_modules/platform-binary": {
                "name": "platform-binary",
                "version": "3.0.0",
            },
            "node_modules/test-helper": {
                "name": "test-helper",
                "version": "4.0.0",
            },
            "node_modules/optional-helper": {
                "name": "optional-helper",
                "version": "5.0.0",
            },
            "node_modules/host-library": {
                "name": "host-library",
                "version": "6.0.0",
            },
        },
    }
    parsed = parse_manifest("package-lock.json", json.dumps(payload))
    assert [(package.name, package.direct) for package in parsed.packages] == [
        ("alpha", True),
        ("alpha", False),
        ("beta", False),
        ("platform-binary", False),
        ("test-helper", True),
        ("optional-helper", True),
        ("host-library", True),
    ]
    assert [
        (
            dependency.name,
            dependency.specifier,
            dependency.relationship,
            dependency.target_location,
        )
        for dependency in parsed.packages[0].dependencies
    ] == [("beta", "^2", "dependency", "node_modules/beta")]
    assert parsed.packages[0].location == "node_modules/alpha"
    assert parsed.packages[0].direct_relationships == ("dependency",)
    host = next(
        package for package in parsed.packages if package.name == "host-library"
    )
    assert host.direct_relationships == ("peer",)


def test_package_lock_v1_uses_legacy_root_dependencies() -> None:
    payload = {
        "lockfileVersion": 1,
        "dependencies": {
            "alpha": {
                "version": "1.2.0",
                "dependencies": {"beta": {"version": "2.0.1"}},
            }
        },
    }
    parsed = parse_manifest("package-lock.json", json.dumps(payload))
    assert [
        (package.name, package.direct, package.location) for package in parsed.packages
    ] == [
        ("alpha", True, "node_modules/alpha"),
        ("beta", False, "node_modules/alpha/node_modules/beta"),
    ]
    assert parsed.packages[0].dependencies[0].target_location == (
        "node_modules/alpha/node_modules/beta"
    )


def test_package_lock_resolves_workspace_links_and_marks_them_direct() -> None:
    payload = {
        "lockfileVersion": 3,
        "packages": {
            "": {"dependencies": {"workspace-package": "file:packages/workspace"}},
            "node_modules/workspace-package": {
                "resolved": "packages/workspace",
                "link": True,
            },
            "packages/workspace": {
                "name": "workspace-package",
                "version": "1.0.0",
                "dependencies": {"child": "^2"},
            },
            "node_modules/child": {"name": "child", "version": "2.0.0"},
        },
    }

    parsed = parse_manifest("package-lock.json", json.dumps(payload))
    workspace = next(
        package for package in parsed.packages if package.name == "workspace-package"
    )

    assert workspace.location == "packages/workspace"
    assert workspace.direct
    assert workspace.direct_relationships == ("dependency",)
    assert workspace.dependencies[0].target_location == "node_modules/child"


def test_uv_lock_parses_parent_relationships() -> None:
    parsed = parse_manifest(
        "uv.lock",
        '[[package]]\nname="project"\nversion="0.1.0"\nsource={editable="."}\ndependencies=[{name="alpha"}]\n[[package]]\nname="alpha"\nversion="1.0.0"\ndependencies=[{name="beta"}]\n[[package]]\nname="beta"\nversion="2.0.0"\n',
    )
    assert len(parsed.packages) == 2
    assert parsed.packages[0].direct
    assert [
        (dependency.name, dependency.specifier)
        for dependency in parsed.packages[0].dependencies
    ] == [("beta", "")]


def test_nuget_lock_parses_frameworks() -> None:
    payload = {
        "dependencies": {
            "net8.0": {
                "Direct.Package": {
                    "type": "Direct",
                    "resolved": "1.2.3",
                    "dependencies": {"Child.Package": "2.0.0"},
                },
                "Child.Package": {"type": "Transitive", "resolved": "2.0.0"},
            }
        }
    }
    parsed = parse_manifest("src/packages.lock.json", json.dumps(payload))
    assert {package.name for package in parsed.packages} == {
        "Direct.Package",
        "Child.Package",
    }
    assert next(
        package for package in parsed.packages if package.name == "Direct.Package"
    ).direct


def test_update_classification() -> None:
    assert classify_update("1.2.3", "2.0.0") == "major"
    assert classify_update("1.2.3", "1.3.0") == "minor"
    assert classify_update("1.2.3", "1.2.4") == "patch"
    assert classify_update("1.2.3", "1.2.3") is None
