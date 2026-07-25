from streamlit.testing.v1 import AppTest


def test_streamlit_chat_runs_a_safe_multi_source_query() -> None:
    app = AppTest.from_file("src/pricing_copilot/streamlit_app.py", default_timeout=10)
    app.run()

    assert not app.exception
    assert len(app.chat_input) == 1
    app.chat_input[0].set_value("Show claims and conversion performance")
    app.run()

    assert not app.exception
    assert len(app.chat_message) == 3
    assert len(app.dataframe) == 2
    markdown = "\n".join(item.value for item in app.markdown)
    assert "Getting information from claims performance data" in markdown
    assert "Getting information from conversion performance data" in markdown
