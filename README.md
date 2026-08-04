# Geografías censales reconciliadas con IGN

Proceso de preparación geoespacial que vincula radios y fracciones censales de Argentina con referencias administrativas del Instituto Geográfico Nacional (IGN).

> **Estado:** productor histórico reutilizable. El repositorio fue actualizado por última vez en agosto de 2025; el entorno, las URLs de descarga y los outputs no fueron revalidados en 2026. Las geometrías corresponden a vintages censales históricos, no a límites administrativos corrientes.

## Producto principal

El pipeline genera archivos con el patrón:

```text
radios_IGN_<year>
```

Estos artefactos combinan identificadores y geometrías para provincia, departamento, fracción y radio censal. La documentación histórica del proyecto reporta 52.401 unidades geográficas únicas en el producto reconciliado; esa cifra debería verificarse al regenerar los datos.

## Qué hace el proceso

Los notebooks implementan tres etapas conceptuales:

1. **Adquisición:** descarga geometrías censales e información del IGN.
2. **Agregación:** disuelve radios hacia fracciones y departamentos.
3. **Reconciliación:** usa intersecciones espaciales para resolver identificadores faltantes o inconsistentes entre fuentes.

El output está pensado para análisis que necesitan una geografía censal navegable dentro de una referencia administrativa común.

## Uso del snapshot

Quien solo necesita las geometrías procesadas puede consumir los archivos publicados sin ejecutar los notebooks. Registrar siempre:

- año censal;
- fuente de cada geometría;
- sistema de referencia de coordenadas;
- commit del repositorio;
- reglas de reconciliación aplicadas.

## Regeneración

La ejecución requiere un entorno geoespacial con Jupyter y GeoPandas. Una instalación moderna puede comenzar con:

```bash
conda create -n censo-geo python=3.11 geopandas jupyter
conda activate censo-geo
jupyter lab
```

Después, ejecutar los notebooks en el orden de adquisición, disolución y reconciliación que indica su contenido. No se recomienda reutilizar instrucciones antiguas basadas en wheels manuales de GDAL: primero debe probarse una instalación reproducible con Conda/Mamba o un contenedor.

## Autoridad y límites

Este repositorio posee la **transformación y el snapshot reconciliado**. No posee las geometrías oficiales ni sustituye la documentación de INDEC, IGN o CEUR-CONICET.

Antes de usarlo para decisiones actuales, considerar:

- cambios de límites desde el censo correspondiente;
- geometrías faltantes o inválidas;
- intersecciones ambiguas;
- diferencias entre identificadores censales y administrativos;
- efectos de CRS, tolerancias y simplificación.

## Próxima revisión útil

1. identificar con precisión fuentes y vintages de cada input;
2. fijar un entorno ejecutable;
3. publicar conteos y cobertura por etapa;
4. registrar excepciones de reconciliación;
5. emitir un manifest del output con checksum y CRS.

## Posible cambio de nombre

`geoespacial-censo-IGN` comunica los ingredientes, pero `censo-arg-geografias` o `censo-ign-geografias` serían más fáciles de encontrar y mantener como nombre de producto.
