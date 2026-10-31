frappe.pages['dashboard-movimientos'].on_page_load = async function (wrapper) {
    await frappe.require("ie_assets.bundle.js");
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Dashboard de Control',
        single_column: true
    });

    // Guardamos referencia al wrapper
    page.wrapper = $(wrapper);
    page.opening_dialog = false;

    // --- 0. Helper: Cargar Filtros Guardados ---
    let saved_filters = JSON.parse(localStorage.getItem('dashboard_movimientos_filters') || '{}');
    let route_opts = frappe.route_options || {};

    let def_sucursal = route_opts.sucursal || saved_filters.sucursal;
    let def_desde = route_opts.from_date || saved_filters.from_date;
    let def_hasta = route_opts.to_date || saved_filters.to_date || frappe.datetime.get_today();

    // --- 1. Agregar Filtros ---
    page.sucursal_field = page.add_field({
        fieldname: 'sucursal',
        label: 'Sucursal',
        fieldtype: 'Link',
        options: 'Branch',
        change: function () {
            refresh_dashboard();
        }
    });

    page.desde_field = page.add_field({
        fieldname: 'fecha_desde',
        label: 'Desde',
        fieldtype: 'Date',
        default: def_desde,
        change: function () {
            refresh_dashboard();
        }
    });

    page.hasta_field = page.add_field({
        fieldname: 'fecha_hasta',
        label: 'Hasta',
        fieldtype: 'Date',
        default: def_hasta,
        change: function () {
            refresh_dashboard();
        }
    });

    page.moneda_field = page.add_field({
        fieldname: 'moneda', label: 'Moneda (vacío: todas)', fieldtype: 'Link', options: 'Currency',
        default: route_opts.moneda || saved_filters.moneda, change: () => refresh_dashboard()
    });
    // Intentar obtener las sucursales permitidas para el usuario
    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Branch",
            fields: ["name"],
            limit_page_length: 50
        },
        callback: function (r) {
            let branches = r.message || [];
            if (branches.length === 1) {
                // Solo una sucursal permitida
                page.sucursal_field.set_input(branches[0].name);
                page.sucursal_field.$input.prop('disabled', true);
            } else {
                // Varias sucursales: intentar usar guardada, URL o default
                let target_branch = def_sucursal || frappe.defaults.get_user_default("Branch");

                // Verificar permisos sobre la target_branch (si está en la lista retornada)
                // Nota: get_list filtra por permisos, así que si está en 'branches', tenemos permiso.
                let branch_exists = branches.find(b => b.name === target_branch);

                if (branch_exists) {
                    page.sucursal_field.set_input(target_branch);
                } else if (branches.length > 0) {
                    // Si la guardada no es válida, usar la primera disponible
                    page.sucursal_field.set_input(branches[0].name);
                }
            }
            // Primera carga
            refresh_dashboard();
        }
    });

    // --- 2. Estructura del Cuerpo del Dashboard ---
    $(wrapper).find('.layout-main-section').append(`
        <style>
            .dashboard-kpi-grid {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                grid-auto-rows: 1fr;
                gap: 16px;
                margin-bottom: 30px;
            }
            .dashboard-kpi-grid .dashboard-card-bg {
                display: flex;
                flex-direction: column;
                min-width: 0;
                padding: 20px;
                border: 1px solid;
                border-radius: 8px;
                transition: transform 0.2s;
            }
            .dashboard-kpi-grid .dashboard-card-bg:hover {
                transform: translateY(-2px);
            }
            .dashboard-kpi-grid h5 {
                margin: 0;
            }
            .dashboard-kpi-grid .dashboard-kpi-value {
                margin: 10px 0 12px;
                font-size: clamp(1.15rem, 1.8vw, 1.6rem);
                font-weight: bold;
                line-height: 1.25;
                font-variant-numeric: tabular-nums;
                overflow-wrap: anywhere;
            }
            .dashboard-kpi-detail {
                margin-top: auto;
                min-height: 2.8em;
                font-size: 11px;
                line-height: 1.4;
                overflow-wrap: anywhere;
                opacity: 0.8;
            }
            .quick-actions-container .btn {
                margin-bottom: 5px;
            }
            @media (max-width: 1199px) {
                .dashboard-kpi-grid {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }
            }
            @media (max-width: 767px) {
                .dashboard-container {
                    padding: 10px !important;
                }
                .quick-actions-container {
                    flex-direction: column;
                }
                .quick-actions-container .btn {
                    width: 100%;
                    text-align: left;
                }
                .dashboard-kpi-grid {
                    grid-template-columns: minmax(0, 1fr);
                }
                .dashboard-kpi-grid .dashboard-kpi-value {
                    font-size: 1.6rem;
                }
                /* Ocultar columnas menos importantes en móvil */
                .hidden-xs {
                    display: none !important;
                }
            }
        </style>
		<div class="dashboard-container" style="padding: 20px;">
			<!-- Sección de Acciones Rápidas -->
			<div class="row" style="margin-bottom: 30px;">
				<div class="col-md-12">
					<h4>Acciones Rápidas</h4>
					<div class="quick-actions-container" style="display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap;">
						<button class="btn btn-primary btn-lg" id="btn-registrar-entrada">
							<span class="fa fa-plus"></span> Registrar Entrada
						</button>
						<button class="btn btn-danger btn-lg" id="btn-registrar-salida">
							<span class="fa fa-minus"></span> Registrar Salida
						</button>
						<button class="btn btn-secondary btn-lg" id="btn-realizar-cierre">
							<span class="fa fa-lock"></span> Realizar Cierre
						</button>
					</div>
				</div>
			</div>

			<h4 id="consolidado-label">Consolidado en moneda base</h4>
            <!-- Sección de Tarjetas KPI -->
            <div class="dashboard-kpi-grid">
                <div class="dashboard-card-bg" style="background: #e2e3e5; border-color: #d6d8db; color: #383d41;">
                    <h5>Saldo Anterior</h5>
                    <h2 id="kpi-saldo-anterior" class="dashboard-kpi-value">0.00</h2>
                    <div class="dashboard-kpi-detail" aria-hidden="true"></div>
                </div>
                <div class="dashboard-card-bg" style="background: #d4edda; border-color: #c3e6cb; color: #155724;">
                    <h5>Total Ingresos</h5>
                    <h2 id="kpi-ingresos" class="dashboard-kpi-value">0.00</h2>
                    <div id="kpi-ingresos-detail" class="dashboard-kpi-detail"></div>
                </div>
                <div class="dashboard-card-bg" style="background: #f8d7da; border-color: #f5c6cb; color: #721c24;">
                    <h5>Total Egresos</h5>
                    <h2 id="kpi-egresos" class="dashboard-kpi-value">0.00</h2>
                    <div id="kpi-egresos-detail" class="dashboard-kpi-detail"></div>
                </div>
                <div class="dashboard-card-bg" style="background: #cce5ff; border-color: #b8daff; color: #004085;">
                    <h5>Saldo Actual</h5>
                    <h2 id="kpi-saldo" class="dashboard-kpi-value">0.00</h2>
                    <div class="dashboard-kpi-detail" aria-hidden="true"></div>
                </div>
            </div>

            <h4>Saldos por moneda</h4>
            <div class="table-responsive"><table class="table table-bordered" id="table-monedas">
                <thead><tr><th>Moneda</th><th>Saldo Anterior</th><th>Ingresos</th><th>Egresos</th><th>Saldo Actual</th></tr></thead>
                <tbody></tbody>
            </table></div>
            <!-- Tabla de Últimos Movimientos -->
			<div class="row">
				<div class="col-md-12">
					<h4>Últimos Movimientos</h4>
					<div class="table-responsive">
						<table class="table table-bordered table-hover" id="table-movimientos">
							<thead class="thead-light">
								<tr>
									<th>Fecha</th>
									<th>Tipo</th>
									<th>Clasificación</th>
                                    <th class="hidden-xs">Referencia</th>
                                    <th class="hidden-xs">Descripción</th>
									<th>Moneda</th><th>Monto</th>
									<th>Estado</th>
                                    <th>Acciones</th>
								</tr>
							</thead>
							<tbody>
								<tr><td colspan="9" class="text-center">Seleccione una sucursal para ver datos</td></tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</div>
	`);

    // --- 3. Funciones de Botones ---
    page.wrapper.find('#btn-registrar-entrada').on('click', function () {
        show_quick_entry_dialog('Ingreso');
    });

    page.wrapper.find('#btn-registrar-salida').on('click', function () {
        show_quick_entry_dialog('Egreso');
    });

    page.wrapper.find('#btn-realizar-cierre').on('click', function () {
        realizar_cierre();
    });

    // --- 4. Lógica de Datos ---
    function get_sucursal() {
        return page.sucursal_field.get_value();
    }

    function refresh_dashboard() {
        const request_id = page.dashboard_request = (page.dashboard_request || 0) + 1;
        let sucursal = page.sucursal_field.get_value();
        let from_date = page.desde_field.get_value();
        let to_date = page.hasta_field.get_value();
        let moneda = page.moneda_field.get_value();

        // Guardar persistencia de filtros
        if (sucursal) {
            localStorage.setItem('dashboard_movimientos_filters', JSON.stringify({
                sucursal: sucursal,
                from_date: from_date,
                to_date: to_date,
                moneda: moneda
            }));
        }

        if (!sucursal) {
            $('#table-monedas tbody').empty();
            $('#kpi-ingresos-detail, #kpi-egresos-detail').empty();
            $('#kpi-ingresos').html(format_currency(0));
            $('#kpi-egresos').html(format_currency(0));
            $('#kpi-saldo-anterior').html(format_currency(0));
            $('#kpi-saldo').html(format_currency(0));
            $('#table-movimientos tbody').html('<tr><td colspan="9" class="text-center">Seleccione una sucursal para ver datos</td></tr>');
            return;
        }

        frappe.call({
            method: "ingresos_egresos.ingresos_y_egresos.page.dashboard_movimientos.dashboard_movimientos.get_dashboard_data",
            args: {
                sucursal: sucursal,
                from_date: from_date,
                to_date: to_date,
                moneda: moneda
            },
            callback: function (r) {
                if (request_id !== page.dashboard_request) return;
                if (r.message) {
                    page.base_currency = r.message.moneda_base;
                    $('#consolidado-label').text('Consolidado en ' + page.base_currency);
                    update_currency_totals(r.message.por_moneda);
                    update_kpis(r.message.totales);
                    update_table(r.message.movimientos);
                }
            }
        });
    }

    function update_currency_totals(rows) {
        const tbody = $('#table-monedas tbody').empty();
        (rows || []).forEach(row => {
            const tr = $('<tr>').appendTo(tbody);
            $('<td>').text(row.moneda).appendTo(tr);
            ['saldo_anterior', 'ingresos', 'egresos', 'saldo'].forEach(key => {
                $('<td class="text-right">').html(format_currency(row[key], row.moneda)).appendTo(tr);
            });
        });
        if (!rows || !rows.length) tbody.append('<tr><td colspan="5">No hay movimientos</td></tr>');
    }

    function update_kpis(totales) {
        $('#kpi-saldo-anterior').html(format_currency(totales.saldo_anterior));
        $('#kpi-ingresos').html(format_currency(totales.ingresos));
        $('#kpi-egresos').html(format_currency(totales.egresos));
        $('#kpi-saldo').html(format_currency(totales.saldo));

        // Actualizar detalles (breakdown)
        if (totales.detalles) {
            let i_vinc = format_currency(totales.detalles.ingresos_vinc);
            let i_pend = format_currency(totales.detalles.ingresos_pend);
            let e_vinc = format_currency(totales.detalles.egresos_vinc);
            let e_pend = format_currency(totales.detalles.egresos_pend);

            $('#kpi-ingresos-detail').html(`Vinc: ${i_vinc} | Pend: ${i_pend}`);
            $('#kpi-egresos-detail').html(`Vinc: ${e_vinc} | Pend: ${e_pend}`);

            // Forzar que los divs internos sean inline para que no rompan la línea
            $('#kpi-ingresos-detail div, #kpi-egresos-detail div').css('display', 'inline');
        }

        if (totales.saldo < 0) {
            $('#kpi-saldo').css('color', '#dc3545'); // Rojo si negativo
        } else {
            $('#kpi-saldo').css('color', '#004085'); // Azul del tema si positivo
        }

        if (totales.saldo_anterior < 0) {
            $('#kpi-saldo-anterior').css('color', '#dc3545');
        } else {
            $('#kpi-saldo-anterior').css('color', '#383d41');
        }
    }

    function update_table(movimientos) {
        let tbody = $('#table-movimientos tbody');
        tbody.empty();

        if (!movimientos || movimientos.length === 0) {
            tbody.append('<tr><td colspan="9" class="text-center">No hay movimientos recientes</td></tr>');
            return;
        }

        movimientos.forEach(mov => {
            let badge_class = mov.tipo === 'Ingreso' ? 'badge-success' : 'badge-danger';
            let estado = mov.vinculado ? '<span class="badge badge-secondary">Cerrado</span>' : '<span class="badge badge-info">Pendiente</span>';

            let btn_action = '';
            if (mov.vinculado) {
                btn_action = `<button class="btn btn-xs btn-default btn-view-mov" data-name="${mov.name}"><i class="fa fa-eye"></i></button>`;
            } else {
                btn_action = `<button class="btn btn-xs btn-default btn-edit-mov" data-name="${mov.name}"><i class="fa fa-pencil"></i></button>`;
            }

            let row = `<tr>
				<td>${frappe.datetime.str_to_user(mov.fecha_de_registro)}</td>
				<td><span class="badge ${badge_class}">${mov.tipo}</span></td>
				<td>${mov.clasificacion || ''}</td>
                <td class="hidden-xs">${mov.referencia || ''}</td>
                <td class="hidden-xs">${mov.descripcion || ''}</td>
				<td>${frappe.utils.escape_html(mov.moneda || "")}</td><td class="text-right font-weight-bold">${format_currency(mov.importe, mov.moneda)}</td>
				<td>${estado}</td>
                <td class="text-center">${btn_action}</td>
			</tr>`;
            tbody.append(row);
        });

        // Bind events
        tbody.find('.btn-view-mov').on('click', function () {
            let name = $(this).data('name');
            show_edit_dialog(name, true);
        });

        tbody.find('.btn-edit-mov').on('click', function () {
            let name = $(this).data('name');
            show_edit_dialog(name, false);
        });
    }

    function movement_dialog_layout(fields, tipo, doc = {}, read_only = false) {
        const controls = Object.fromEntries(fields.filter(field => field.fieldname).map(field => [field.fieldname, field]));
        controls.moneda_base.hidden = 1;
        if (page.base_currency) controls.importe_base.label = `Importe base (${page.base_currency})`;
        controls.descripcion.max_height = '90px';
        return [
            {fieldtype: 'Section Break', label: 'Datos del movimiento'},
            controls.sucursal, controls.fecha_de_registro,
            {fieldtype: 'Column Break'}, controls.clasificacion, controls.referencia,
            {fieldtype: 'Section Break', label: 'Importe y moneda'},
            controls.importe, controls.tasa_de_cambio,
            {fieldtype: 'Column Break'}, controls.moneda, controls.importe_base, controls.moneda_base,
            ...frappe.ie_assets.fields(tipo, doc, read_only),
            {fieldtype: 'Section Break', label: 'Descripción y soportes'}, controls.descripcion,
            {fieldtype: 'Column Break'},
            ...fields.filter(field => ['file_upload_area', 'existing_attachments', 'new_file_upload_area'].includes(field.fieldname))
        ];
    }

    function show_quick_entry_dialog(tipo) {
        if (page.opening_dialog || (cur_dialog && cur_dialog.display)) return;

        let sucursal = get_sucursal();
        if (!sucursal) {
            frappe.msgprint("Por favor, seleccione una sucursal primero.");
            return;
        }

        page.opening_dialog = true;
        // Obtener opciones de clasificación primero
        frappe.call({
            method: 'ingresos_egresos.ingresos_y_egresos.doctype.movimiento.movimiento.get_code_name_options',
            args: { code_name: tipo },
            callback: function (r_opts) {
                page.opening_dialog = false;
                let clasif_options = r_opts.message || [];

                let d = new frappe.ui.Dialog({
                    title: `Registrar ${tipo}`,
                    size: 'large',
                    fields: movement_dialog_layout([
                        {
                            label: 'Sucursal',
                            fieldname: 'sucursal',
                            fieldtype: 'Link',
                            options: 'Branch',
                            default: sucursal,
                            read_only: 1
                        },
                        {
                            label: 'Fecha',
                            fieldname: 'fecha_de_registro',
                            fieldtype: 'Date',
                            default: frappe.datetime.get_today(),
                            reqd: 1
                        },
                        {
                            label: 'Clasificación',
                            fieldname: 'clasificacion',
                            fieldtype: 'Select',
                            options: clasif_options,
                            reqd: 1
                        },
                        {
                            label: 'Referencia',
                            fieldname: 'referencia',
                            fieldtype: 'Data'
                        },
                        {
                            label: 'Importe',
                            fieldname: 'importe',
                            fieldtype: 'Currency',
                            options: 'moneda',
                            reqd: 1
                        },
                        ...frappe.ie_currency.fields(),
                        {
                            label: 'Descripción',
                            fieldname: 'descripcion',
                            fieldtype: 'Small Text'
                        },
                        {
                            fieldtype: 'Section Break',
                            label: 'Adjuntos'
                        },
                        {
                            fieldname: 'file_upload_area',
                            fieldtype: 'HTML',
                            label: 'Soportes (Drag & Drop)'
                        }
                    ], tipo),
                    primary_action_label: 'Registrar',
                    primary_action: function (values) {
                        values.tipo = tipo;
                        create_movimiento(d, values);
                    }
                });

                frappe.ie_currency.bind_dialog(d);
                frappe.ie_assets.bind(d);
                // ... (Drag & Drop rendering code) ...
                let $wrapper = d.fields_dict.file_upload_area.$wrapper;
                $wrapper.html(`
                    <div class="file-drop-zone" style="border: 2px dashed #ccc; border-radius: 8px; padding: 20px; text-align: center; background: #f9f9f9; cursor: pointer;">
                        <div style="font-size: 24px; margin-bottom: 10px;"><i class="fa fa-cloud-upload"></i></div>
                        <p style="margin: 0;">Arrastra tus archivos aquí o haz clic para subir</p>
                        <input type="file" id="file-input-hidden" multiple style="display: none;">
                        <div id="file-preview-list" style="margin-top: 10px; text-align: left;"></div>
                    </div>
                `);

                let pending_files = [];
                let $dropZone = $wrapper.find('.file-drop-zone');
                let $fileInput = $wrapper.find('#file-input-hidden');
                let $previewList = $wrapper.find('#file-preview-list');

                $dropZone.on('dragover', function (e) { e.preventDefault(); e.stopPropagation(); $(this).css({ 'background': '#e9ecef', 'border-color': '#007bff' }); });
                $dropZone.on('dragleave', function (e) { e.preventDefault(); e.stopPropagation(); $(this).css({ 'background': '#f9f9f9', 'border-color': '#ccc' }); });
                $dropZone.on('drop', function (e) {
                    e.preventDefault(); e.stopPropagation(); $(this).css({ 'background': '#f9f9f9', 'border-color': '#ccc' });
                    handle_files(e.originalEvent.dataTransfer.files);
                });
                $dropZone.on('click', function () { $fileInput.click(); });
                $fileInput.on('click', function (e) { e.stopPropagation(); });
                $fileInput.on('change', function () { handle_files(this.files); });

                function handle_files(files) {
                    for (let i = 0; i < files.length; i++) {
                        pending_files.push(files[i]);
                        $previewList.append(`<div style="background: #fff; border: 1px solid #ddd; padding: 5px; margin-bottom: 5px;">${files[i].name}</div>`);
                    }
                }

                d.pending_files = pending_files;
                d.show();
            }
        });
    }

    function show_edit_dialog(name, read_only) {
        if (page.opening_dialog || (cur_dialog && cur_dialog.display)) return;
        page.opening_dialog = true;

        frappe.db.get_doc('Movimiento', name).then(doc => {
            read_only = read_only || Boolean(doc.turno_pos) || doc.estado_contable === 'Contabilizado';
            // Obtener opciones de clasificación
            frappe.call({
                method: 'ingresos_egresos.ingresos_y_egresos.doctype.movimiento.movimiento.get_code_name_options',
                args: { code_name: doc.tipo },
                callback: function (r_opts) {
                    page.opening_dialog = false;
                    let clasif_options = r_opts.message || [];
                    if (doc.clasificacion && !clasif_options.includes(doc.clasificacion)) clasif_options.push(doc.clasificacion);

                    // Obtener adjuntos existentes
                    frappe.call({
                        method: 'frappe.client.get_list',
                        args: {
                            doctype: 'File',
                            filters: {
                                attached_to_doctype: 'Movimiento',
                                attached_to_name: name
                            },
                            fields: ['name', 'file_name', 'file_url']
                        },
                        callback: function (r_files) {
                            let attachments = r_files.message || [];

                            let fields = [
                                {
                                    label: 'Sucursal',
                                    fieldname: 'sucursal',
                                    fieldtype: 'Link',
                                    options: 'Branch',
                                    default: doc.sucursal,
                                    read_only: 1
                                },
                                {
                                    label: 'Fecha',
                                    fieldname: 'fecha_de_registro',
                                    fieldtype: 'Date',
                                    default: doc.fecha_de_registro,
                                    reqd: 1,
                                    read_only: read_only
                                },
                                {
                                    label: 'Referencia',
                                    fieldname: 'referencia',
                                    fieldtype: 'Data',
                                    default: doc.referencia,
                                    read_only: read_only
                                },
                                {
                                    label: 'Clasificación',
                                    fieldname: 'clasificacion',
                                    fieldtype: 'Select',
                                    options: clasif_options,
                                    default: doc.clasificacion,
                                    reqd: 1,
                                    read_only: read_only
                                },
                                {
                                    label: 'Importe',
                                    fieldname: 'importe',
                                    fieldtype: read_only ? 'Float' : 'Currency',
                                    precision: frappe.boot.sysdefaults.currency_precision || 2,
                                    options: 'moneda',
                                    default: doc.importe,
                                    reqd: 1,
                                    read_only: read_only
                                },
                                ...frappe.ie_currency.fields(doc, read_only),
                                {
                                    label: 'Descripción',
                                    fieldname: 'descripcion',
                                    fieldtype: 'Small Text',
                                    default: doc.descripcion,
                                    read_only: read_only
                                },
                                {
                                    fieldtype: 'Section Break',
                                    label: 'Adjuntos'
                                },
                                {
                                    fieldname: 'existing_attachments',
                                    fieldtype: 'HTML',
                                    label: 'Archivos Existentes'
                                }
                            ];

                            if (!read_only) {
                                fields.push({
                                    fieldname: 'new_file_upload_area',
                                    fieldtype: 'HTML',
                                    label: 'Agregar Archivos'
                                });
                            }

                            let d = new frappe.ui.Dialog({
                                title: read_only ? `Ver ${doc.tipo}` : `Editar ${doc.tipo}`,
                                size: 'large',
                                fields: movement_dialog_layout(fields, doc.tipo, doc, read_only),
                                primary_action_label: read_only ? null : 'Guardar Cambios',
                                secondary_action_label: read_only || doc.asiento_contable ? null : 'Eliminar Registro',
                                secondary_action: function () {
                                    frappe.confirm('¿Está seguro de que desea eliminar este registro?', () => {
                                        frappe.call({
                                            method: 'frappe.client.delete',
                                            args: {
                                                doctype: 'Movimiento',
                                                name: doc.name
                                            },
                                            callback: function (r) {
                                                if (!r.exc) {
                                                    frappe.show_alert({ message: __('Registro eliminado'), indicator: 'green' });
                                                    d.hide();
                                                    refresh_dashboard();
                                                }
                                            }
                                        });
                                    });
                                },
                                primary_action: function (values) {
                                    if (!read_only) {
                                        frappe.call({
                                            method: 'frappe.client.set_value',
                                            args: {
                                                doctype: 'Movimiento',
                                                name: doc.name,
                                                fieldname: {
                                                    fecha_de_registro: values.fecha_de_registro,
                                                    referencia: values.referencia,
                                                    clasificacion: values.clasificacion,
                                                    importe: values.importe,
                                                    moneda: values.moneda,
                                                    tasa_de_cambio: values.tasa_de_cambio,
                                                    descripcion: values.descripcion
                                                }
                                            },
                                            callback: function (r) {
                                                if (!r.exc) {
                                                    // Subir nuevos archivos si los hay
                                                    if (d.pending_files && d.pending_files.length > 0) {
                                                        upload_files(doc.doctype, doc.name, d.pending_files, function () {
                                                            frappe.msgprint('Movimiento actualizado');
                                                            d.hide();
                                                            refresh_dashboard();
                                                        });
                                                    } else {
                                                        frappe.msgprint('Movimiento actualizado');
                                                        d.hide();
                                                        refresh_dashboard();
                                                    }
                                                }
                                            }
                                        });
                                    } else {
                                        d.hide();
                                    }
                                }
                            });

                            if (!read_only) {
                                d.get_secondary_btn().addClass('btn-danger').css('color', 'white');
                            }

                            // Renderizar Archivos Existentes
                            let $attach_wrapper = d.fields_dict.existing_attachments.$wrapper;
                            let html = '<div class="list-group" style="margin-bottom: 15px;">';
                            if (attachments.length === 0) {
                                html += '<div class="list-group-item font-italic text-muted">No hay adjuntos</div>';
                            } else {
                                attachments.forEach(f => {
                                    html += `<div class="list-group-item d-flex justify-content-between align-items-center" id="file-${f.name}">
                                    <div>
                                        <i class="fa fa-paperclip text-muted mr-2"></i>
                                        <a href="${f.file_url}" target="_blank">${f.file_name}</a>
                                    </div>
                                    ${!read_only ? `<button class="btn btn-xs btn-danger btn-delete-file" data-name="${f.name}" title="Eliminar"><i class="fa fa-times"></i></button>` : ''}
                                </div>`;
                                });
                            }
                            html += '</div>';
                            $attach_wrapper.html(html);

                            if (!read_only) {
                                // Evento Eliminar
                                $attach_wrapper.find('.btn-delete-file').on('click', function () {
                                    let file_name = $(this).data('name');
                                    frappe.confirm('¿Eliminar este archivo adjunto?', () => {
                                        frappe.call({
                                            method: 'frappe.client.delete',
                                            args: {
                                                doctype: 'File',
                                                name: file_name
                                            },
                                            callback: function (r) {
                                                if (!r.exc) {
                                                    $attach_wrapper.find(`#file-${file_name}`).remove();
                                                    frappe.show_alert('Archivo eliminado');
                                                }
                                            }
                                        });
                                    });
                                });

                                // Configurar Drag & Drop para Nuevos
                                let $upload_wrapper = d.fields_dict.new_file_upload_area.$wrapper;
                                $upload_wrapper.html(`
                            <div class="file-drop-zone" style="border: 2px dashed #ccc; border-radius: 8px; padding: 15px; text-align: center; background: #f9f9f9; cursor: pointer;">
                                <div style="font-size: 20px; margin-bottom: 5px;"><i class="fa fa-cloud-upload"></i></div>
                                <p style="margin: 0; font-size: 12px;">Arrastra archivos aquí o haz clic</p>
                                <input type="file" id="file-input-edit" multiple style="display: none;">
                                <div id="file-preview-edit" style="margin-top: 10px; text-align: left;"></div>
                            </div>
                        `);

                                let pending_files = [];
                                let $dropZone = $upload_wrapper.find('.file-drop-zone');
                                let $fileInput = $upload_wrapper.find('#file-input-edit');
                                let $previewList = $upload_wrapper.find('#file-preview-edit');

                                $dropZone.on('dragover', function (e) { e.preventDefault(); e.stopPropagation(); $(this).css({ 'background': '#e9ecef', 'border-color': '#007bff' }); });
                                $dropZone.on('dragleave', function (e) { e.preventDefault(); e.stopPropagation(); $(this).css({ 'background': '#f9f9f9', 'border-color': '#ccc' }); });
                                $dropZone.on('drop', function (e) {
                                    e.preventDefault(); e.stopPropagation(); $(this).css({ 'background': '#f9f9f9', 'border-color': '#ccc' });
                                    handle_edit_files(e.originalEvent.dataTransfer.files);
                                });
                                $dropZone.on('click', function () { $fileInput.click(); });
                                $fileInput.on('click', function (e) { e.stopPropagation(); });
                                $fileInput.on('change', function () { handle_edit_files(this.files); });

                                function handle_edit_files(files) {
                                    for (let i = 0; i < files.length; i++) {
                                        pending_files.push(files[i]);
                                        $previewList.append(`<div style="background: #fff; border: 1px solid #ddd; padding: 4px; margin-bottom: 4px; font-size: 12px;">${files[i].name}</div>`);
                                    }
                                }

                                d.pending_files = pending_files;
                            }

                            frappe.ie_currency.bind_dialog(d, doc, read_only);
                            if (!read_only) frappe.ie_assets.bind(d, doc);
                            d.show();
                        }
                    });
                }
            });
        });
    }

    function create_movimiento(dialog, values) {
        frappe.call({
            method: 'frappe.client.insert',
            args: {
                doc: {
                    doctype: 'Movimiento',
                    sucursal: values.sucursal,
                    tipo: values.tipo,
                    fecha_de_registro: values.fecha_de_registro,
                    clasificacion: values.clasificacion,
                    referencia: values.referencia,
                    importe: values.importe,
                    moneda: values.moneda,
                    tasa_de_cambio: values.tasa_de_cambio,
                    descripcion: values.descripcion,
                    docstatus: 0 // Crear como Borrador (0)
                }
            },
            freeze: true,
            freeze_message: 'Registrando...',
            callback: function (r) {
                if (!r.exc) {
                    let doc = r.message;
                    if (dialog.pending_files && dialog.pending_files.length > 0) {
                        upload_files(doc.doctype, doc.name, dialog.pending_files, function () {
                            frappe.msgprint(`Movimiento registrado con éxito.`);
                            dialog.hide();
                            refresh_dashboard();
                        });
                    } else {
                        frappe.msgprint(`Movimiento registrado con éxito.`);
                        dialog.hide();
                        refresh_dashboard();
                    }
                }
            }
        });
    }

    function upload_files(doctype, docname, files, on_complete) {
        if (!files || files.length === 0) {
            if (on_complete) on_complete();
            return;
        }

        let uploaded = 0;
        let total = files.length;

        files.forEach(file => {
            let formData = new FormData();
            formData.append('file', file, file.name);
            formData.append('doctype', doctype);
            formData.append('docname', docname);
            formData.append('is_private', 1);

            $.ajax({
                type: 'POST',
                url: '/api/method/upload_file',
                headers: {
                    'X-Frappe-CSRF-Token': frappe.csrf_token
                },
                data: formData,
                processData: false,
                contentType: false,
                success: function (data) {
                    console.log("File uploaded:", data);
                },
                error: function (request, status, error) {
                    frappe.msgprint(__("Error uploading file: {0}", [file.name]));
                    console.error(error);
                },
                complete: function () {
                    uploaded++;
                    if (uploaded === total) {
                        if (on_complete) on_complete();
                    }
                }
            });
        });
    }

    function realizar_cierre() {
        if (page.opening_dialog || (cur_dialog && cur_dialog.display)) return;

        let sucursal = get_sucursal();
        if (!sucursal) {
            frappe.msgprint("Seleccione una sucursal primero");
            return;
        }

        show_cierre_dialog(sucursal);
    }

    function show_cierre_dialog(sucursal) {
        const d = new frappe.ui.Dialog({
            title: 'Realizar Cierre de Movimientos',
            fields: [
                {label: 'Sucursal', fieldname: 'sucursal', fieldtype: 'Link', options: 'Branch', default: sucursal, read_only: 1},
                {label: 'Moneda', fieldname: 'moneda', fieldtype: 'Link', options: 'Currency', reqd: 1,
                    onchange: async () => {
                        const moneda = d.get_value('moneda');
                        const seq = d._closure_seq = (d._closure_seq || 0) + 1;
                        if (!moneda) return;
                        const r = await frappe.call({
                            method: 'ingresos_egresos.ingresos_y_egresos.doctype.registro_de_cierre_de_movimiento.registro_de_cierre_de_movimiento.get_closure_defaults',
                            args: {sucursal, moneda}
                        });
                        if (seq !== d._closure_seq) return;
                        d.set_value('fecha_inicio', r.message.fecha_inicio);
                        d.set_df_property('fecha_inicio', 'read_only', r.message.hay_cierre ? 1 : 0);
                    }},
                {label: 'Fecha Inicio', fieldname: 'fecha_inicio', fieldtype: 'Date', reqd: 1},
                {label: 'Fecha Final', fieldname: 'fecha_final', fieldtype: 'Date', default: frappe.datetime.get_today(), reqd: 1}
            ],
            primary_action_label: 'Generar Cierre',
            primary_action(values) {
                if (values.fecha_inicio > values.fecha_final) {
                    frappe.msgprint('La Fecha Inicio no puede ser mayor que la Fecha Final');
                    return;
                }
                frappe.confirm(`¿Generar el cierre del ${values.fecha_inicio} al ${values.fecha_final} en ${frappe.utils.escape_html(values.moneda)}?`, () => create_cierre(d, values));
            }
        });
        frappe.ie_currency.settings().then(settings => d.set_value('moneda', page.moneda_field.get_value() || settings.moneda_base));
        d.show();
    }

    function create_cierre(dialog, values) {
        frappe.call({
            method: 'frappe.client.insert',
            args: {
                doc: {
                    doctype: 'Registro de Cierre de Movimiento',
                    sucursal: values.sucursal,
                    fecha_inicio: values.fecha_inicio,
                    fecha_final: values.fecha_final,
                    moneda: values.moneda,
                    docstatus: 1 // Submit inmediato para aplicar cambios
                }
            },
            freeze: true,
            freeze_message: 'Procesando Cierre...',
            callback: function (r) {
                if (!r.exc) {
                    let doc_link = frappe.utils.get_form_link(r.message.doctype, r.message.name);
                    frappe.msgprint(`Cierre ${doc_link} realizado correctamente.`);
                    dialog.hide();
                    refresh_dashboard();
                }
            }
        });
    }

    function format_currency(value, currency, decimals) {
        return frappe.format(value, {fieldtype: 'Currency', options: 'moneda'},
            {only_value: true}, {moneda: currency || page.base_currency});
    }

    // Init
    if (page.sucursal_field.get_value()) {
        refresh_dashboard();
    }
}
