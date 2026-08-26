# Evidencia histórica

Este directorio conserva materiales anteriores a la arquitectura actual de **Argentina Geography**.

Los notebooks bajo `legacy/notebooks/` documentan la evolución del proyecto original `censo-ign-geografias`: descarga de insumos, disolución de áreas censales, superposición con departamentos IGN y exploraciones previas. Se preservan como **evidencia metodológica y de regresión**, no como interfaces de producción ni como autoridad silenciosa sobre fuentes, geometrías o políticas actuales.

La superficie soportada del repositorio vive en `src/`, `config/`, `releases/`, `tests/` y la documentación técnica bajo `docs/`. Para reproducir productos actuales, use los comandos y releases documentados allí.

## Notebooks preservados

- `01 - Descarga de geometrias (IGN, Censo CONICET).ipynb`
- `02 - Disolución de áreas del Censo.ipynb`
- `03 - Radios censales en Departamentos IGN.ipynb`
- `Notebook.ipynb`

Estos archivos pueden contener URLs históricas, rutas locales, decisiones exploratorias, celdas de detención deliberada y transformaciones que la arquitectura actual no adopta. No deben ejecutarse de punta a punta para producir releases actuales.

Los checkpoints de Jupyter no se preservan como artefactos independientes: eran copias editoriales redundantes y no etapas adicionales del proceso histórico.
