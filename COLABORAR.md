# Colaborar con Geografías de Argentina

Gracias por acercar evidencia, correcciones o casos de uso. Este proyecto busca que las geografías argentinas sean reproducibles, verificables e interoperables sin ocultar diferencias entre fuentes.

No hace falta conocer la arquitectura interna para colaborar. Sí ayuda traer una **pregunta concreta** y la mejor evidencia disponible.

## Quiero reportar una fuente o una nueva versión

Incluí, si está disponible:

- organismo o proveedor;
- nombre exacto de la capa, archivo o servicio;
- URL o localizador oficial;
- fecha de consulta o publicación;
- versión, vintage, commit o identificador de dataset;
- identificadores nativos relevantes;
- licencia o términos de distribución conocidos;
- qué necesidad concreta resolvería incorporarla.

Una URL “actual” sin versión ni evidencia de identidad puede servir como pista, pero no alcanza para una release científica reproducible.

## Quiero reproducir una release

Indicá:

- `dataset_id` y `release_version` si los conocés;
- sistema operativo y versión de Python;
- comando ejecutado;
- resultado esperado y observado;
- manifiesto, hashes o fragmento de QA relevante;
- si la falla ocurre en adquisición de fuente, materialización o verificación offline.

No adjuntes microdatos restringidos ni archivos cuya redistribución no esté permitida.

## Quiero aportar QA o señalar un problema geométrico

Son especialmente útiles los reportes que identifican:

- feature o identificador nativo;
- fuente y vintage exactos;
- tipo de problema: geometría inválida, hueco, duplicado, CRS, identificador, cobertura, relación inesperada, etc.;
- evidencia cuantitativa o ejemplo mínimo reproducible;
- si el problema está en la fuente o fue introducido por el procesamiento.

El proyecto no aplica reparaciones espaciales silenciosas. Si una corrección cambia la geometría sustantivamente, debe quedar explícita y revisable.

## Quiero consumir una geografía o relación

Contanos el uso concreto y el grano que necesitás. En general el consumidor debería poder trabajar con:

```text
geography_uid / source_uid
+ atributos
+ geometry
```

o, para relaciones:

```text
source_uid
+ target_uid
+ hechos de relación
```

Los consumidores deberían fijar una release exacta y verificar su manifiesto/hash. No es necesario importar el código de este repositorio para usar los artefactos.

## Quiero proponer una relación entre geografías

Describí:

- las dos geografías exactas que querés relacionar;
- la pregunta de investigación o aplicación;
- si necesitás hechos N:M o una política que elija un único destino;
- qué métricas serían relevantes: intersección, cobertura, proporción de área, membership, etc.

Por defecto, una relación N:M se conserva como N:M. Un crosswalk que selecciona un destino requiere una necesidad concreta y una política explícita; no se deriva automáticamente de “mayor solapamiento”.

## Pull requests

Un PR pequeño y fácil de revisar suele incluir:

1. una sola misión;
2. fuente/autoridad de entrada claramente identificada;
3. artefacto o documentación resultante;
4. invariantes y no-objetivos;
5. tests o evidencia de verificación cuando corresponda;
6. limitaciones y puntos que requieren revisión humana.

Cambios de semántica de fuente, licencias, identidad nativa, reparación geométrica sustantiva o políticas de adjudicación necesitan revisión humana explícita.

## Qué no promete el proyecto

- incorporar toda fuente sugerida;
- elegir una única frontera correcta;
- inferir permisos de redistribución;
- convertir diferencias entre proveedores en errores de uno de ellos;
- mantener crosswalks “convenientes” sin un consumidor real.

Una contribución también puede ser simplemente una buena evidencia de que **no** conviene integrar una fuente o política.
