# Análisis de Datos — FarmaPulse

Este documento resume el análisis exploratorio realizado sobre los datos recolectados por el pipeline de scraping nocturno de FarmaPulse.

## Contexto

FarmaPulse ejecuta un scraping automatizado cada noche (vía GitHub Actions) sobre Inkafarma, Mifarma y Farmacia Universal, registrando precios de medicamentos en distintos distritos de Lima. Cada ejecución queda registrada en `scrapes_log_rows.csv`, incluyendo si la búsqueda encontró resultados (`encontrado`) y cuántos productos devolvió (`cantidad_resultados`).

## Metodología

El análisis se realizó en Python (pandas) sobre el archivo `scrapes_log_rows.csv`, evaluando:
1. Tasa de éxito general del scraping
2. Farmacias con mayor cantidad de fallos (búsquedas sin resultados)
3. Promedio de resultados obtenidos cuando la búsqueda sí encuentra el medicamento

El notebook completo con el código y las celdas ejecutadas está en este mismo folder (`farmapulse_analysis.ipynb`).

## Resultados

| Métrica | Valor |
|---|---|
| Tasa de éxito global del scraping | 92.95% |
| Farmacias con más fallos | ID 2 y 12 (52 fallos cada una) |
| Promedio de resultados por búsqueda exitosa | 13.2 productos |

## Hallazgos

- El pipeline tiene una tasa de éxito alta (~93%), lo que indica que el scraping es estable en la mayoría de los casos.
- Las farmacias con ID **2** y **12** concentran la mayor cantidad de búsquedas fallidas, empatadas en 52 casos cada una — esto sugiere revisar si esas fuentes cambiaron su estructura HTML o si aplican bloqueos al scraper con más frecuencia.
- La farmacia con ID **1** también presenta fallos (28), aunque en menor proporción.
- Cuando la búsqueda es exitosa, se obtiene en promedio 13.2 resultados por producto, lo cual da una buena base de comparación de precios para el usuario final.

## Próximos pasos sugeridos

- Investigar la causa específica de los fallos en las farmacias ID 2 y 12 (posible cambio de estructura web o rate-limiting).
- Añadir alertas automáticas si la tasa de éxito de una farmacia cae por debajo de un umbral (ej. 70%).
- Repetir este análisis periódicamente para monitorear la salud del pipeline en el tiempo.

