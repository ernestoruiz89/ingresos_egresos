# Ingresos y Egresos (Frappe App)

Una aplicación poderosa y optimizada para el control y gestión de **Ingresos y Egresos** financieros, construida sobre el framework **Frappe/ERPNext v16.50+**. Diseñada para ofrecer una experiencia de usuario fluida con dashboards interactivos y reportes analíticos avanzados.

## 🚀 Características Principales

### 📊 Dashboard Interactivo
- **Vista General**: Visualiza KPIs en tiempo real de Ingresos, Egresos y Saldo actual por sucursal.
- **Acciones Rápidas**: Registra entradas y salidas directamente desde el dashboard.
- **Drag & Drop**: Sube soportes y evidencia (imágenes/PDFs) arrastrándolos directamente al registrar un movimiento.
- **Cierre Rápido**: Realiza el cierre de caja de movimientos pendientes sin salir de la pantalla principal.
- **Seguridad**: Filtro de sucursal inteligente basado en los permisos del usuario.

### 📝 Gestión de Movimientos
- **Validaciones Avanzadas**: 
  - Prevención de registros en periodos cerrados.
  - Verificación cronológica contra el primer cierre.
  - Optimizaciones de base de datos para alto rendimiento.
- **Tipos de Movimiento**: Ingresos y Egresos con clasificación detallada.

### 📈 Reportes Analíticos
- **Reporte de Flujo de Caja**: 
  - Análisis diario de entradas, salidas y flujo neto.
  - Cálculo automático de saldo acumulado con indicadores visuales de estado.
  - Gráficos combinados de barras y líneas.
- **Reporte por Concepto**:
  - Análisis de distribución de gastos/ingresos.
  - Gráfico de dona para visualizar la participación porcentual por categoría.
- **Reporte de Movimientos**: Listado detallado para auditoría.

## 🛠️ Tecnologías

- **Framework**: Frappe / ERPNext (>= v16.50.0 y < v17)
- **Lenguaje**: Python 3.14 (Backend), JavaScript (Frontend)
- **Base de Datos**: MariaDB

## 📦 Instalación

1.  Asegúrate de tener **Frappe Bench** instalado.
2.  Obtén la app en tu bench:

```bash
bench get-app https://github.com/ernestoruiz89/ingresos_egresos.git
```

3.  Instala la app en tu sitio:

```bash
bench --site [tu-sitio] install-app ingresos_egresos
```

4.  Reinicia el bench (si es necesario):

```bash
bench restart
```

## 📄 Licencia

MIT
## Multimoneda

Configure **IE Configuración → Moneda Base** antes de registrar movimientos o migrar datos históricos. Una vez existan movimientos o cierres, esta moneda queda bloqueada.

Cada movimiento guarda su moneda, la tasa (unidades de moneda base por una unidad de la moneda del movimiento) y el importe convertido. La tasa se consulta en ERPNext para la fecha del movimiento y se puede corregir manualmente; si no hay tasa disponible, debe introducirse una tasa positiva. La moneda base siempre utiliza tasa 1. Los importes consolidados usan las tasas guardadas, sin revalorizar saldos históricos.

El tablero muestra saldos por moneda y el consolidado en moneda base. En Flujo de Caja y Movimientos por Concepto, deje el filtro Moneda vacío para consolidar o seleccione una moneda para ver sus importes originales. El Reporte de Movimientos conserva ambas columnas para auditoría. Los totales y saldos incluyen borradores activos y movimientos cerrados; excluyen cancelados.

Los cierres se realizan por sucursal y moneda, en orden cronológico. Se pueden cerrar dos monedas en las mismas fechas. Para cancelar un cierre anterior, primero cancele los cierres posteriores de la misma sucursal y moneda.

### Actualización de una instalación existente

Haga un respaldo del sitio, configure la moneda base y ejecute desde el bench:

```bash
bench --site <sitio> migrate
bench build --app ingresos_egresos
```

La migración asigna moneda base y tasa 1 a los movimientos sin moneda o tasa válida, conserva los importes originales y reconstruye los totales de los cierres. Si un cierre histórico vincula monedas incompatibles, la migración se detiene e identifica el cierre para corregirlo. Puede volver a ejecutarse sin duplicar movimientos ni filas de cierre.

### Pruebas

En un sitio de prueba con ERPNext y esta aplicación instalados:

```bash
bench --site <sitio-de-prueba> run-tests --module ingresos_egresos.tests.test_multicurrency --skip-before-tests
node --test ingresos_egresos/tests/test_currency_client.cjs
```

## Módulos y menús en Frappe 16

La aplicación aparece en el escritorio con su propio icono. Incluye acceso al espacio de trabajo y al tablero; su Dock contiene el módulo **Ingresos y Egresos**. La barra lateral reúne Inicio, Tablero, Movimientos, Cierres, Reportes y Configuración, incluida la moneda base.

La navegación se distribuye como documentos estándar `Sidebar` y `Dock`, compatibles con la navegación de Frappe 16.50+. `bench --site <sitio> migrate` sincroniza estos documentos y el espacio de trabajo en una aplicación ya instalada. No se requiere volver a instalarla ni ejecutar conversiones globales de los menús del sitio.

Los enlaces respetan los permisos existentes de cada usuario; mostrar la aplicación no concede permisos de lectura o escritura. Las personalizaciones de navegación del sitio y del usuario se conservan mediante las capas nativas de Frappe.

Para verificar los menús después de migrar un sitio de prueba:

```bash
bench --site <sitio-de-prueba> run-tests --module ingresos_egresos.tests.test_navigation --skip-before-tests
```

Validado con Frappe 16.52.0 y ERPNext 16.51.1.

## Integración opcional con el POS de ERPNext

La integración se instala desactivada. Después de actualizar el código, ejecute `bench --site <sitio> migrate`, `bench build --app ingresos_egresos` y reinicie los servicios del bench. No se modifican archivos de ERPNext ni se asocian automáticamente facturas o movimientos históricos.

### Configuración

1. Configure la moneda base en **IE Configuración**. Quedará bloqueada cuando haya movimientos, cierres o turnos POS.
2. Cierre todos los POS de ERPNext y los movimientos pendientes de las sucursales que va a vincular. Resuelva los cierres integrados incompletos.
3. En **Configuración y POS**, relacione cada **POS Profile** con su **Sucursal** y active **Integrar con POS de ERPNext**. Un perfil sin vínculo no podrá abrirse mientras esté activa la integración.
4. Asigne **IE Cajero POS** a los operadores, junto con sus permisos habituales del POS. Limite perfiles mediante los usuarios del POS Profile y **User Permissions**. Limite sucursales y empresas mediante User Permissions sobre **Branch** y **Company**, aplicables a **IE Turno POS** o a todos los documentos.
5. Para cerrar, el usuario necesita además crear y enviar **POS Closing Entry** en ERPNext; para anular necesita su permiso de cancelación y **IE Supervisor POS**. El rol de esta app no concede esos permisos contables ni acceso al maestro de Recursos Humanos. Los supervisores también respetan los perfiles, sucursales y empresas autorizados.

Activar, desactivar o modificar los vínculos exige las mismas condiciones del paso 2. No cambie el modo de facturación de POS Settings ni la empresa, moneda o medios de pago del perfil mientras tenga turnos pendientes. Cada turno conserva una copia de su configuración y fondo inicial.

### Operación y arqueo

Dentro del POS, el menú **Ingresos y Egresos** ofrece **Registrar ingreso**, **Registrar egreso**, **Movimientos y saldos** y **Cierre conjunto** mediante modales. Los movimientos manuales solicitan concepto, importe, moneda, tasas, medio de pago, referencia y descripción. El servidor fija el turno, cajero, sucursal y fecha/hora. Estas operaciones no generan asientos ni documentos contables adicionales.

Los formularios de ingreso y egreso se organizan en bloques y dos columnas en escritorio, tanto en el POS como en el tablero. En móvil se adaptan a una columna. El tablero conserva los soportes y el importe base en el mismo formulario.

Las facturas confirmadas de **POS Invoice** y de **Sales Invoice** creadas desde el POS registran los pagos efectivamente cobrados, separados por medio, descontando el vuelto. Las devoluciones restan y las facturas anuladas durante el turno invalidan sus movimientos. La consolidación posterior no vuelve a registrar esos cobros. Se instalan los conceptos **Ventas POS** y **Devoluciones POS** sin sobrescribir conceptos personalizados.

El saldo esperado es **fondo inicial + ventas cobradas − devoluciones + ingresos manuales − egresos manuales**. El fondo proviene de la apertura, en moneda de la empresa, y no se cuenta como ingreso. El reporte muestra cada moneda y medio de pago, un consolidado en moneda base, filtros y páginas de 25 movimientos. Las tasas guardadas se conservan sin revalorizar. Si la moneda de la empresa difiere de la moneda base de la app, ambos importes y tasas quedan guardados. El arqueo de ERPNext solicita importes contados por medio de pago en **moneda de la empresa** y conserva las diferencias.

Cada turno se identifica por su **POS Opening Entry**. Se admiten varios turnos diarios, turnos que cruzan medianoche o mes y varios perfiles en una sucursal. Los cierres generales excluyen los movimientos de turnos POS. Cada cierre integrado conserva apertura, horas exactas y moneda; un turno vacío también genera constancia de cierre.

### Recuperación de cierres y anulación

Al confirmar **Cierre conjunto**, el turno bloquea operaciones y guarda el progreso antes de enviar el cierre a ERPNext. Solo después de que ERPNext termine realmente, incluidos sus trabajos en cola, se crean todos los cierres de la app. Hasta completar ambas etapas se bloquea una nueva apertura del **mismo perfil**. Otros perfiles pueden continuar.

Mantenga activos los workers y el scheduler habituales de Frappe/ERPNext. La reconciliación se ejecuta al actualizar la apertura y cada minuto desde el servidor; no depende del navegador. Si el proceso queda **En cola**, revise los trabajos de ERPNext y sus workers. Si aparece **Error**, corrija la causa indicada y use **Cierre conjunto → Reintentar / Actualizar**, desde el POS o desde **Turnos POS**. Reintentar conserva el cierre ya enviado a ERPNext y no duplica movimientos ni cierres de la app. Un fallo de ERPNext requiere un reintento explícito; la finalización pendiente de la app se puede recuperar automáticamente.

Las API se publican bajo `/api/method/ingresos_egresos.pos`: `context`, `rates`, `report` y `status` consultan el turno autorizado; `register_movement`, `start_closing`, `retry` y `cancel_closing` exigen POST. Cada registro manual requiere un `request_id` estable para reconocer reintentos. Los permisos y estados se validan también desde estas API y los formularios de documentos.

Un supervisor autorizado puede usar **Turnos POS → Anular cierre conjunto** únicamente si no hay un turno posterior del mismo perfil. Primero se anula ERPNext; cuando termine, se anulan los cierres de la app y se reabre el turno original. Mientras se procesa la anulación, las operaciones permanecen bloqueadas. Si falla, se reintenta desde el mismo turno. Los documentos y cierres cancelados conservan su historial. No cambie estados ni desvincule movimientos manualmente para recuperar un turno.

### Validación en un sitio aislado

```bash
bench --site <sitio-de-prueba> run-tests --module ingresos_egresos.tests.test_pos_integration
bench --site <sitio-de-prueba> run-tests --module ingresos_egresos.tests.test_multicurrency --skip-before-tests
bench --site <sitio-de-prueba> run-tests --module ingresos_egresos.tests.test_navigation --skip-before-tests
node --test ingresos_egresos/tests/test_pos_client.cjs ingresos_egresos/tests/test_currency_client.cjs
```

Ejecute las suites de base de datos secuencialmente, en un sitio sin cajas abiertas ajenas a las pruebas. Las pruebas POS incluyen facturas reales en ambos modos, pagos mixtos, vuelto, devoluciones, cobro parcial, dos monedas base distintas, diferencias, turnos vacíos, aislamiento de permisos, consolidación, cierres y anulaciones en cola y recuperación tras fallar la segunda etapa. Antes de activar en otra instalación, compruebe sus perfiles, cuentas, permisos, tasas, workers y arqueo dentro de los modales.
