from coding import agent_tools


def test_docs_come_from_the_installed_version_and_suggest_close_names():
    text = agent_tools.library_docs("json.dumps")
    assert text.startswith("json.dumps") and "sort_keys" in text
    assert agent_tools.library_docs("json.dump_s") == "NO EXISTE json.dump_s. Parecidos en json: dumps, dump"
    assert "no se puede importar" in agent_tools.library_docs("paquete_que_no_existe.x")
    assert "nombre completo" in agent_tools.library_docs("import os; os.system('x')")


def test_the_tool_is_offered_to_the_agent():
    import agent_mcp
    assert any(tool["name"] == "docs" for tool in agent_mcp.TOOLS)
