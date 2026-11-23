# Documentación del Multiagent SCADA PID

Los archivos Markdown de primer nivel en `agents/` son agentes especialistas.
Las políticas compartidas se guardan en `agents/policies/` y se inyectan en el
prompt global sin ser tratadas como agentes. Los manuales RAG están en
`knowledge_base/`.

La implementación del cargador se encuentra en
`backend/ai/multiagent/system.py`.
