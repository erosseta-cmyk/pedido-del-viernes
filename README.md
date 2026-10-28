# Pedido del Viernes

Catálogo de pedidos semanales. La página es `index.html` y se publica con GitHub Pages.

Todos los días a las 9:00 (hora de Chile) una tarea automática revisa los precios de las distribuidoras, ajusta los precios de venta en el mismo porcentaje y vuelve a publicar la página. Si algo sale raro (una distribuidora no responde, un precio salta más de 25 %, un producto se agota), se abre un aviso en **Issues** y GitHub manda un correo.

- Cambiar textos, reglas (mínimo, despacho, horarios) o datos bancarios: `build/template.html`, bloque "Reglas".
- Cambiar nombres, categorías o quitar productos: `build/catalog.json`.
- Forzar una actualización: pestaña **Actions → Actualizar precios → Run workflow**.
