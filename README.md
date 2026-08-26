# Geografías de Argentina

**Argentina Geography** publica geografías argentinas reproducibles y versionadas, junto con relaciones espaciales explícitas entre fuentes oficiales y curadas.

El proyecto integra evidencia de **INDEC**, **IGN**, **CEUR-CONICET**, la geografía oficial de **EPH-INDEC** y circuitos electorales curados por **Tartagalensis** sin convertirlas en una única frontera “verdadera”. Cada producto conserva su proveedor, versión o snapshot, identificadores nativos, limitaciones y controles de calidad.

## Qué publica este repositorio

La interfaz pública estable son **artefactos versionados con manifiestos y catálogos**. Los consumidores no necesitan importar el código de este repositorio ni reconstruir geometrías por su cuenta.

- **Geography Release**: una geografía de una fuente y versión exactas, normalizada sin cambiar silenciosamente su significado.
- **Relation Release**: hechos espaciales entre dos releases exactas. Una relación N:M sigue siendo N:M.
- **Crosswalk Release**: una interpretación opcional, sólo cuando existe una política explícita que necesita resolver una relación hacia un destino determinado.

GeoParquet es el formato analítico preferido para geometrías; Parquet para relaciones tabulares; GeoJSON puede publicarse como derivado de intercambio o visualización.

## Familias de productos actuales

La arquitectura actual cubre, entre otros productos:

- radios censales oficiales de INDEC 2022;
- geografías censales 2010 y 2022 de CEUR-CONICET, mantenidas como autoridades independientes;
- geografía oficial de referencia EPH basada en radios del Censo 2010;
- departamentos administrativos de IGN vinculados a una geografía censal exacta mediante hechos de relación;
- circuitos electorales 2021 y 2025 de Tartagalensis;
- relaciones Censo ↔ circuitos electorales sin adjudicar silenciosamente un “ganador”;
- relaciones entre releases censales y entre proveedores, preservando diferencias y ambigüedades.

Los identificadores exactos de release, hashes, fuentes, QA y limitaciones viven en los catálogos, manifiestos y documentos de producto bajo `docs/` y `releases/`.

## Principios

1. **No existe una geografía canónica única de Argentina.** Una geometría de IGN no “corrige” una de INDEC, ni viceversa.
2. **La procedencia es parte del dato.** Fuente, vintage, snapshot, hashes e identificadores nativos se conservan.
3. **Las relaciones no son adjudicaciones.** Superposición, multiplicidad, huecos y ambigüedad se publican como hechos inspeccionables.
4. **No hay reparación espacial silenciosa.** Buffer, snapping, nearest-neighbour, centroides, `make_valid` sustantivo o umbrales requieren una política explícita y observable.
5. **Los consumidores reciben artefactos.** La lógica científica de pobreza, muestreo, modelos de ingreso o resultados electorales pertenece a los repositorios consumidores.

## Uso y verificación

Para desarrollar o verificar la superficie actual:

```bash
python -m pip install -e ".[dev]"
make check
make test
```

Los comandos que acceden a fuentes reales son explícitos y separados de los tests offline. Cada fuente tiene reglas propias de distribución: que el repositorio pueda recuperar y verificar una fuente no implica que pueda redistribuirla.

## Documentación técnica

Para entender la arquitectura y los límites de autoridad, leer:

1. [`docs/ARGENTINA_GEOGRAPHY_ARCHITECTURE.md`](docs/ARGENTINA_GEOGRAPHY_ARCHITECTURE.md)
2. [`docs/SOURCE_AUTHORITY_MATRIX.md`](docs/SOURCE_AUTHORITY_MATRIX.md)
3. [`docs/PRODUCT_MODEL.md`](docs/PRODUCT_MODEL.md)
4. [`docs/MIGRATION_AND_REPO_CONSOLIDATION.md`](docs/MIGRATION_AND_REPO_CONSOLIDATION.md)
5. documentos de producto, handoffs y evidencia de fuente bajo [`docs/`](docs/)

`AGENTS.md` y los execution packs describen el contrato de trabajo interno para cambios automatizados; no son necesarios para consumir releases publicados.

## Historia del proyecto

El repositorio comenzó como `censo-ign-geografias`, un flujo exploratorio para combinar geografía censal e IGN. Esos notebooks y snapshots históricos se preservan como evidencia y material de regresión, pero no constituyen la interfaz productiva actual ni autoridad silenciosa sobre decisiones modernas.

La arquitectura vigente separa explícitamente proveedores, fuentes, releases y relaciones. `empirical-data-contracts` aporta vocabulario compartido de identidad/procedencia y `spatial-data-foundation` aporta mecánicas espaciales neutrales; este repositorio concentra el conocimiento específico de fuentes y geografías argentinas.

## Alcance y responsabilidad

Argentina Geography no publica estadísticas oficiales ni elige por defecto una frontera “correcta”. Su objetivo es que geografías y relaciones relevantes para investigación y aplicaciones argentinas sean **descubribles, reproducibles, verificables e interoperables**.
