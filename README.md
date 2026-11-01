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

Dentro del POS, el menú **Ingresos y Egresos** ofrece **Registrar ingreso**, **Registrar egreso**, **Movimientos y saldos** y **Cierre conjunto** mediante modales. Los movimientos manuales solicitan concepto, importe, moneda, tasas, medio de pago, referencia y descripción. El servidor fija el turno, cajero, sucursal y fecha/hora. Registrar el movimiento no genera asientos automáticamente; su contabilización posterior es una acción explícita desde Movimiento o su lista.

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

## Contabilización de movimientos

Después de actualizar, ejecute `bench --site <sitio> migrate`, `bench build --app ingresos_egresos` y reinicie los servicios. La actualización añade los campos y vínculos; no contabiliza movimientos históricos.

En **IE Configuración → Contabilidad por sucursal y moneda**, añada una fila por sucursal y moneda, con empresa, cuenta de caja o banco y, opcionalmente, centro de costos predeterminado. La cuenta debe estar habilitada, ser de detalle y tener esa moneda. En una tienda con POS, use la cuenta que corresponde al medio de pago del perfil en ERPNext para que sus saldos contables concilien. La configuración actual permite una sola cuenta por sucursal y moneda; si varios medios usan cuentas diferentes, la contabilización manual de esta app utiliza siempre esa cuenta configurada.

El formulario **Movimiento** separa sus datos, **Contabilidad** y **Seguimiento** en pestañas. Use **Contabilidad → Contabilizar**, o seleccione hasta 100 filas en la lista y pulse **Contabilizar seleccionados**. Se propone la cuenta del concepto, si está configurada para la empresa. El modal permite revisar cuenta contrapartida, centro de costos y tasa contable. Las cuentas por cobrar o pagar solicitan tipo de tercero y tercero antes de contabilizar; si un lote está incompleto, se conserva la revisión y no se crea ningún asiento hasta completarlo. Abra la fila con el lápiz para completar sus datos.

Se confirma un **Journal Entry** por movimiento: ingreso debita caja y acredita ingreso; egreso debita gasto y acredita caja. Las cuentas por cobrar/pagar conservan el tercero. Los cobros a clientes y pagos a proveedores sin factura vinculada quedan como anticipos sin aplicar para conciliarlos posteriormente con las herramientas de ERPNext. Este formulario no realiza aplicación a facturas ni calcula impuestos de compras.

La moneda original y la tasa guardada se conservan. Si la empresa contable usa otra moneda distinta de la base de la app, el modal consulta la tasa de ERPNext para la fecha del movimiento y permite completarla; el servidor valida y guarda la conversión contable por separado. Los reintentos y lotes superpuestos omiten los registros ya contabilizados. Un error al crear un asiento o activo revierte todo el lote.

**Asiento contable** queda visible y enlazado en el documento y en la lista, junto con clasificación, moneda e importe. Los cobros y devoluciones automáticos del POS se muestran como **Gestionado por POS** y se omiten: su factura ya realiza la contabilidad. Los movimientos manuales del POS pueden contabilizarse expresamente; esta acción no vuelve a alterar el saldo esperado ni el arqueo.

El usuario debe tener escritura sobre Movimiento, creación y envío de Journal Entry, y lectura sobre la empresa, cuentas, centro de costos y tercero utilizados. Los movimientos POS validan además el alcance autorizado del turno. Los roles de cajero/supervisor de esta app no otorgan automáticamente permisos contables. La contabilización usa los permisos y validaciones nativos de ERPNext, incluidos períodos contables y dimensiones adicionales configuradas en el sitio.

Un movimiento contabilizado queda bloqueado para cambios financieros. Para corregirlo, anule primero su asiento con los permisos nativos correspondientes; el vínculo y el estado **Asiento anulado** conservan el historial. Después podrá corregirlo si su período sigue abierto y volver a contabilizarlo. El cierre de caja y la contabilización son procesos independientes: un movimiento de un cierre puede contabilizarse después, sin reabrir la caja.

### Egresos que adquieren activos fijos

En un egreso del documento, tablero o POS, active **Es activo fijo**. Se muestran únicamente los datos básicos del activo: artículo, nombre, ubicación, fecha disponible para uso, vida útil en meses y valor residual en la moneda del movimiento. La categoría se obtiene del artículo y su vida útil se sugiere desde la categoría; puede ajustarla antes de registrar. El formulario usa dos columnas en escritorio y se adapta a móvil.

Prepare en ERPNext un **Item** habilitado, marcado como activo fijo y no inventariable, con **Asset Category** y **Location**. En la categoría configure para la empresa las cuentas de activo fijo, depreciación acumulada y gasto de depreciación; estas cuentas usan la moneda de la empresa. El usuario que contabiliza necesita también crear/enviar Asset y Asset Movement. Quien registra debe poder consultar el artículo y la ubicación.

Al contabilizar, el asiento debita la cuenta de activo de **Asset Category** y acredita caja; no usa la cuenta de gasto del concepto. En la misma transacción crea y confirma un **Asset**, enlazado al movimiento y al asiento, con su calendario nativo de depreciación lineal mensual. El valor residual se convierte con la tasa contable. Las categorías no depreciables crean la ficha sin calendario. Cada movimiento representa la adquisición de una unidad de activo.

La adquisición se identifica mediante su asiento confirmado; no se crea una factura de compra ficticia ni se registra como activo de apertura. Una extensión de Asset para Frappe 16 admite esta compra directa también en categorías con CWIP, sin modificar ERPNext ni duplicar la capitalización. El resto del ciclo del activo utiliza los documentos y procesos nativos. ERPNext puede prorratear el primer y último mes según la fecha disponible para uso; mantenga sus workers y scheduler para la [contabilización de depreciaciones](https://docs.frappe.io/erpnext/asset-depreciation).

**Activo fijo vinculado** abre su ficha desde Movimiento. Para anular la adquisición, anule su asiento: se anula también el activo en la misma operación. Si ya tiene depreciaciones contabilizadas, primero anule esas depreciaciones mediante ERPNext. Se conservan los documentos anulados; una nueva contabilización crea documentos nuevos.

### Comprobación de contabilidad y activos

```bash
bench --site <sitio-de-prueba> run-tests --module ingresos_egresos.tests.test_accounting --skip-before-tests
node --test ingresos_egresos/tests/test_currency_client.cjs ingresos_egresos/tests/test_pos_client.cjs ingresos_egresos/tests/test_asset_client.cjs
```

Validado en WSL con Frappe 16.52.0 / ERPNext 16.51.1: asientos y mayor reales, tasas distintas para app y empresa, tercero y centro de costos faltantes, lotes incompletos y reversión ante fallos, compra y primera depreciación nativa de activo, anulación/recontabilización y un turno de tienda con venta, movimientos manuales contabilizados y cierre conciliado. También se probaron dos lotes simultáneos con los mismos movimientos y activo, sin duplicar documentos. Las comprobaciones manuales usan datos de prueba en un sitio aislado.

## Ingresos y gastos diferidos mediante asiento directo

En Movimiento, en los formularios rápidos del tablero o dentro del POS, marque **Distribuir entre meses** y complete **Inicio del servicio** y **Número de meses**. Se admiten entre 1 y 120 meses; el inicio debe ser igual o posterior al movimiento. Esta opción es excluyente con **Es activo fijo** y se aplica únicamente a movimientos manuales.

Al usar **Contabilizar**, revise la **Cuenta a reconocer**, el centro de costos y la **Cuenta diferida**. Esta última se propone desde los campos nativos de Empresa **Default Deferred Expense Account / Default Deferred Revenue Account**. Para un egreso debe ser una cuenta de activo de balance; para un ingreso, de pasivo de balance. No utilice cuentas de caja, banco, clientes, proveedores, inventario o activo fijo como cuenta diferida. Ambas cuentas del calendario deben usar la moneda de la empresa; se mantienen los permisos y las validaciones contables de ERPNext.

El asiento inicial registra el importe completo contra caja y la cuenta diferida. Por ejemplo, un egreso de 1,200 distribuido en 12 meses debita 1,200 al activo diferido y acredita 1,200 a caja; cada cuota debita 100 al gasto y acredita 100 al diferido. Para ingresos se invierte el sentido: caja contra pasivo diferido al cobrar, y pasivo diferido contra ingreso al reconocer. Las cuotas no crean movimientos adicionales ni alteran saldos o arqueos del POS.

**Calendario de diferimiento** en Movimiento abre **IE Diferimiento**, donde se muestran total, reconocido, pendiente, cuotas y sus asientos. Se crean cuotas iguales al último día de cada mes desde el mes de inicio; la última absorbe el redondeo. No se prorratea por días aunque el servicio comience a mitad de mes. La conversión a moneda de empresa se fija en el asiento inicial; las cuotas no consultan tasas posteriores.

**Contabilizar cuotas vencidas** procesa únicamente cuotas cuya fecha ya llegó, usando la fecha del servidor. **Pausar calendario** detiene los reconocimientos; **Reanudar calendario** permite continuarlos. Un doble clic, reintento o proceso concurrente no duplica cuotas. Si falla alguna cuota del lote, se revierten todas las cuotas creadas por esa ejecución y se guarda **Último error** para corregir la causa y reintentar.

La automatización se instala desactivada. Puede activar **IE Configuración → Contabilizar cuotas diferidas automáticamente** para ejecutar el mismo proceso diariamente con el scheduler y workers de Frappe. Cada ejecución atiende hasta 100 calendarios con cuotas vencidas, priorizando los menos recientemente procesados. Usa los permisos actuales del usuario que autorizó cada calendario: si fue deshabilitado, perdió acceso a la sucursal o no puede enviar asientos, se conserva el error y no se contabilizan esas cuotas.

Para corregir un diferimiento, anule sus reconocimientos desde la última cuota contabilizada hacia la primera y después el asiento inicial. Anular una cuota pausa automáticamente el calendario para evitar que el proceso diario la recree; puede reanudarlo expresamente para volver a reconocerla. Los asientos anulados mantienen la referencia al calendario y a su cuota. Anular el asiento inicial marca el calendario como **Anulado**. Una nueva contabilización del movimiento crea un calendario nuevo y conserva el anterior para auditoría.

Este modo usa un calendario de esta app y **Journal Entry** nativos. El [proceso diferido estándar de ERPNext](https://docs.frappe.io/erpnext/deferred-accounting) trabaja con facturas de compra/venta; no procesa estos calendarios ni los incluye en su reporte de diferidos basado en facturas. Las cuotas de esta app se consultan en **IE Diferimiento** y en el mayor contable. No se generan facturas ni se cambian las opciones de diferimiento de Accounts Settings.

La actualización no marca ni contabiliza movimientos históricos como diferidos. Ejecute `bench --site <sitio> migrate`, `bench build --app ingresos_egresos` y reinicie los servicios para instalar los campos y el proceso diario. Los conceptos iniciales se guardan fuera del directorio de fixtures de Frappe para que una migración conserve los conceptos, cuentas y estados personalizados del sitio.

La suite contable incluye reconocimiento de ingresos y gastos, redondeo, multimoneda, cuentas faltantes, cuotas futuras, pausa/reanudación, permisos por sucursal, fallo después de una cuota enviada, anulación y preservación de conceptos al migrar. La suite POS verifica que el reconocimiento mensual posterior al cierre mantiene el arqueo original. Para el cliente incluya también `ingresos_egresos/tests/test_deferred_client.cjs` en el comando `node --test`.

### Carga de formularios después de actualizar

Los componentes de moneda, activos, diferimientos y modales se sirven como archivos JavaScript directos. El tablero los espera y comprueba su disponibilidad antes de habilitar los registros, de modo que un manifiesto de bundles desactualizado no provoque errores al abrir **Registrar Entrada** o **Registrar Salida**. Los puntos de entrada `.bundle.js` se conservan para compatibilidad con páginas ya almacenadas en caché.

Después de actualizar, ejecute los pasos habituales de migración, compilación y reinicio del bench y recargue el navegador con **Ctrl+F5**. Si un componente no pudo descargarse, el tablero muestra un aviso para actualizar y recargar la aplicación. La prueba `node --test ingresos_egresos/tests/test_dashboard_client.cjs` verifica ambos formularios sin bundles compilados, la espera de scripts y el manejo de un archivo ausente.
