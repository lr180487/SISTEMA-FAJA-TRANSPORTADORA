from pathlib import Path

from backend.ai.multiagent.system import MultiAgentRAGSystem


def test_loads_specialists_and_shared_policies() -> None:
    project_root = Path(__file__).resolve().parents[1]
    system = MultiAgentRAGSystem(base_dir=project_root, db_manager=None)

    assert "orquestador" in system.agents
    assert "agente_seguridad_industrial" in system.agents
    assert "agente_integracion_plc" in system.agents
    assert len(system.agent_policies) >= 8
    assert "README" not in system.agents


def test_estop_query_routes_safety_specialist() -> None:
    project_root = Path(__file__).resolve().parents[1]
    system = MultiAgentRAGSystem(base_dir=project_root, db_manager=None)

    selected_ids = {
        agent["id"]
        for agent in system.route_agents(
            "La faja está en E-STOP y presenta una alarma",
            retrieved=[],
            web_used=False,
        )
    }

    assert "orquestador" in selected_ids
    assert "agente_seguridad_industrial" in selected_ids


def test_plc_query_routes_plc_specialist() -> None:
    project_root = Path(__file__).resolve().parents[1]
    system = MultiAgentRAGSystem(base_dir=project_root, db_manager=None)

    selected_ids = {
        agent["id"]
        for agent in system.route_agents(
            "Configurar comunicación OPC UA con PLC Siemens S7-1200",
            retrieved=[],
            web_used=False,
        )
    }

    assert "agente_integracion_plc" in selected_ids


def test_legacy_multiagent_imports_remain_available() -> None:
    from backend.ai.rag_multiagent import MultiAgentRAGSystem as AiLegacy
    from backend.rag_multiagent import MultiAgentRAGSystem as RootLegacy
    from backend.ai.multiagent.system import MultiAgentRAGSystem as Canonical

    assert AiLegacy is Canonical
    assert RootLegacy is Canonical
