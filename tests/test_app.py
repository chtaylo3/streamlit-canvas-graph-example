from streamlit.testing.v1 import AppTest

from streamlit_canvas_graph import PACKAGE_ROOT


def test_streamlit_app_smoke(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SCG_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(PACKAGE_ROOT / "app.py"), default_timeout=30)
    app.run()
    assert not app.exception
    assert app.title[0].value == "GitHub Dependency Explorer"
    assert len(app.metric) == 4
    explore = next(widget for widget in app.selectbox if widget.label == "Explore")
    jump = next(widget for widget in app.selectbox if widget.label == "Jump to node")
    assert explore.value == "repository"
    assert all(
        option == "Search repositories…" or option.endswith(" · repository")
        for option in jump.options
    )

    jump.select("payments-api · repository").run()
    assert not app.exception
    explore = next(widget for widget in app.selectbox if widget.label == "Explore")
    jump = next(widget for widget in app.selectbox if widget.label == "Jump to node")
    assert explore.value == "manifest"
    assert all(
        option == "Search manifests…" or option.endswith(" · manifest")
        for option in jump.options
    )


def test_sibling_settings_persist_by_type_across_navigation(tmp_path, monkeypatch):
    from streamlit_canvas_graph.database import connect, create_demo_dataset
    from streamlit_canvas_graph.settings import reload_config

    database = create_demo_dataset(tmp_path)
    monkeypatch.setenv("SCG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SCG_DATABASE", str(database))
    reload_config()
    with connect(database, read_only=True) as con:
        repos = [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT node_id FROM nodes WHERE node_type='repository' ORDER BY node_id"
            ).fetchall()
        ]
        account = con.execute(
            "SELECT node_id FROM nodes WHERE node_type='account' LIMIT 1"
        ).fetchone()[0]
        manifest = con.execute(
            "SELECT node_id FROM nodes WHERE node_type='manifest' LIMIT 1"
        ).fetchone()[0]
    app = AppTest.from_file(str(PACKAGE_ROOT / "app.py"), default_timeout=30)

    def visit(node):
        app.session_state["focus_id"] = node
        app.session_state["selected_id"] = node
        app.run()
        assert not app.exception

    visit(repos[0])
    app.toggle[0].set_value(True).run()
    app.slider[0].set_value(60).run()
    visit(account)
    assert not app.toggle[0].value
    assert app.slider[0].value == 20
    visit(repos[1])
    assert app.toggle[0].value
    assert app.slider[0].value == 60
    visit(manifest)
    assert not app.toggle[0].value
    app.toggle[0].set_value(True).run()
    app.slider[0].set_value(40).run()
    visit(repos[0])
    assert app.toggle[0].value and app.slider[0].value == 60
    visit(manifest)
    assert app.toggle[0].value and app.slider[0].value == 40
    reload_config()
