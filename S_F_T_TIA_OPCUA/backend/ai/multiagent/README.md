# Multiagent RAG

- `system.py`: servicio principal, sincronización RAG, selección de especialistas y proveedores.
- `markdown.py`: parser de agentes Markdown, normalización, tokenización y extracción PDF/DOCX.
- La carpeta raíz `agents/` contiene especialistas y políticas editables.

El servicio mantiene el contrato `MultiAgentRAGSystem` y se importa desde
`backend.ai.multiagent`.
