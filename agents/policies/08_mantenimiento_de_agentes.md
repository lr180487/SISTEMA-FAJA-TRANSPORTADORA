# Mantenimiento de archivos de agentes

Cada agente especialista se define en un archivo `.md` de primer nivel en `agents/`.
Debe incluir frontmatter YAML simple con `id`, `name`, `role`, `icon` y `keywords`
separadas por comas. El parser actual lee esos campos como texto simple.

Los documentos compartidos se almacenan en `agents/policies/`; el runtime los
inyecta como políticas globales y no los registra como especialistas.

Al añadir un agente:
1. Asignar un `id` único.
2. Definir keywords concretas y no excesivamente genéricas.
3. Describir misión, procedimiento, límites y evidencia requerida.
4. Ejecutar sincronización RAG y probar consultas representativas.
5. Verificar que no desplace agentes críticos por coincidencias demasiado amplias.
