frappe.pages['dashboard-movimientos'].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Dashboard de Control',
        single_column: true
    });

    // Guardamos referencia al wrapper
    page.wrapper = $(wrapper);

    // --- 1. Agregar Filtro de Sucursal ---
    page.sucursal_field = page.add_field({
        fieldname: 'sucursal',
        label: 'Sucursal',
        fieldtype: 'Link',
        options: 'Branch',
        change: function () {
            refresh_dashboard();
        }
    });

    // Intentar obtener las sucursales permitidas para el usuario
    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Branch",
            fields: ["name"],
            limit_page_length: 2 // Solo necesitamos saber si hay 1 o más
        },
        callback: function (r) {
            if (r.message && r.message.length === 1) {
                // Si solo tiene acceso a una, la seleccionamos y bloqueamos el campo
                page.sucursal_field.set_input(r.message[0].name);
                page.sucursal_field.$input.prop('disabled', true);
                refresh_dashboard();
            } else if (frappe.defaults.get_user_default("Branch")) {
                // Si tiene acceso a varias pero tiene un default, lo ponemos (sin bloquear)
                page.sucursal_field.set_input(frappe.defaults.get_user_default("Branch"));
                refresh_dashboard();
            }
        }
    });

    // --- 2. Estructura del Cuerpo del Dashboard ---
    $(wrapper).find('.layout-main-section').append(`
		<div class="dashboard-container" style="padding: 20px;">
			<!-- Sección de Tarjetas KPI -->
			<div class="row" style="margin-bottom: 30px;">
				<div class="col-md-4">
					<div class="dashboard-card-bg" style="background: #d4edda; padding: 20px; border-radius: 8px; border: 1px solid #c3e6cb;">
						<h5 style="color: #155724;">Ingresos (Pendientes)</h5>
						<h2 id="kpi-ingresos" style="font-weight: bold; margin-top: 10px;">$ 0.00</h2>
					</div>
				</div>
				<div class="col-md-4">
					<div class="dashboard-card-bg" style="background: #f8d7da; padding: 20px; border-radius: 8px; border: 1px solid #f5c6cb;">
						<h5 style="color: #721c24;">Egresos (Pendientes)</h5>
						<h2 id="kpi-egresos" style="font-weight: bold; margin-top: 10px;">$ 0.00</h2>
					</div>
				</div>
				<div class="col-md-4">
					<div class="dashboard-card-bg" style="background: #e2e3e5; padding: 20px; border-radius: 8px; border: 1px solid #d6d8db;">
						<h5 style="color: #383d41;">Saldo Actual</h5>
						<h2 id="kpi-saldo" style="font-weight: bold; margin-top: 10px;">$ 0.00</h2>
					</div>
				</div>
			</div>

			<!-- Sección de Acciones Rápidas -->
			<div class="row" style="margin-bottom: 30px;">
				<div class="col-md-12">
					<h4>Acciones Rápidas</h4>
					<div style="display: flex; gap: 10px; margin-top: 10px;">
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
									<th>Concepto</th>
									<th>Monto</th>
									<th>Estado</th>
								</tr>
							</thead>
							<tbody>
								<tr><td colspan="5" class="text-center">Seleccione una sucursal para ver datos</td></tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</div>
	`);

    // --- 3. Funciones de Botones ---
    page.wrapper.find('#btn-registrar-entrada').on('click', function () {
        show_quick_entry_dialog('Entrada');
    });

    page.wrapper.find('#btn-registrar-salida').on('click', function () {
        show_quick_entry_dialog('Salida');
    });

    page.wrapper.find('#btn-realizar-cierre').on('click', function () {
        realizar_cierre();
    });

    // --- 4. Lógica de Datos ---
    function get_sucursal() {
        return page.sucursal_field.get_value();
    }

    function refresh_dashboard() {
        let sucursal = get_sucursal();
        if (!sucursal) {
            $('#kpi-ingresos').text("$ 0.00");
            $('#kpi-egresos').text("$ 0.00");
            $('#table-movimientos tbody').html('<tr><td colspan="5" class="text-center">Seleccione una sucursal para ver datos</td></tr>');
            return;
        }

        frappe.call({
            method: "ingresos_egresos.ingresos_y_egresos.page.dashboard_movimientos.dashboard_movimientos.get_dashboard_data",
            args: {
                sucursal: sucursal
            },
            callback: function (r) {
                if (r.message) {
                    update_kpis(r.message.totales);
                    update_table(r.message.movimientos);
                }
            }
        });
    }

    function update_kpis(totales) {
        $('#kpi-ingresos').html(format_currency(totales.ingresos));
        $('#kpi-egresos').html(format_currency(totales.egresos));
        $('#kpi-saldo').html(format_currency(totales.saldo));

        if (totales.saldo < 0) {
            $('#kpi-saldo').css('color', '#dc3545');
        } else {
            $('#kpi-saldo').css('color', '#28a745');
        }
    }

    function update_table(movimientos) {
        let tbody = $('#table-movimientos tbody');
        tbody.empty();

        if (!movimientos || movimientos.length === 0) {
            tbody.append('<tr><td colspan="5" class="text-center">No hay movimientos recientes</td></tr>');
            return;
        }

        movimientos.forEach(mov => {
            let badge_class = mov.tipo === 'Entrada' ? 'badge-success' : 'badge-danger';
            let estado = mov.vinculado ? '<span class="badge badge-secondary">Cerrado</span>' : '<span class="badge badge-info">Pendiente</span>';

            let row = `<tr>
				<td>${frappe.datetime.str_to_user(mov.fecha_de_registro)}</td>
				<td><span class="badge ${badge_class}">${mov.tipo}</span></td>
				<td>${mov.clasificacion || ''}</td>
				<td class="text-right font-weight-bold">${format_currency(mov.importe)}</td>
				<td>${estado}</td>
			</tr>`;
            tbody.append(row);
        });
    }

    function show_quick_entry_dialog(tipo) {
        let sucursal = get_sucursal();
        if (!sucursal) {
            frappe.msgprint("Por favor, seleccione una sucursal primero.");
            return;
        }

        let d = new frappe.ui.Dialog({
            title: `Registrar ${tipo}`,
            fields: [
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
                    fieldtype: 'Data',
                    reqd: 1
                },
                {
                    label: 'Importe',
                    fieldname: 'importe',
                    fieldtype: 'Currency',
                    reqd: 1
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
            ],
            primary_action_label: 'Registrar',
            primary_action: function (values) {
                values.tipo = tipo;
                create_movimiento(d, values);
            }
        });

        // Renderizar Drag & Drop
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
                    importe: values.importe,
                    docstatus: 1
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
        function upload_next(index) {
            if (index >= files.length) {
                if (on_complete) on_complete();
                return;
            }
            let file = files[index];
            frappe.upload.upload_file(file, {
                doctype: doctype,
                docname: docname,
                is_private: 1
            }, {
                callback: function () {
                    upload_next(index + 1);
                },
                error: function () {
                    // Continue even if error
                    upload_next(index + 1);
                }
            });
        }
        upload_next(0);
    }

    function realizar_cierre() {
        let sucursal = get_sucursal();
        if (!sucursal) {
            frappe.msgprint("Seleccione una sucursal primero");
            return;
        }

        let d = new frappe.ui.Dialog({
            title: 'Realizar Cierre de Movimientos',
            fields: [
                {
                    label: 'Sucursal',
                    fieldname: 'sucursal',
                    fieldtype: 'Link',
                    options: 'Branch',
                    default: sucursal,
                    read_only: 1
                },
                {
                    label: 'Fecha Inicio',
                    fieldname: 'fecha_inicio',
                    fieldtype: 'Date',
                    default: frappe.datetime.get_today(),
                    reqd: 1
                },
                {
                    label: 'Fecha Final',
                    fieldname: 'fecha_final',
                    fieldtype: 'Date',
                    default: frappe.datetime.get_today(),
                    reqd: 1
                },
                {
                    fieldtype: 'HTML',
                    options: '<p class="text-muted small">Esto vinculará todos los movimientos pendientes en el rango de fechas seleccionado.</p>'
                }
            ],
            primary_action_label: 'Generar Cierre',
            primary_action: function (values) {
                if (values.fecha_inicio > values.fecha_final) {
                    frappe.msgprint("La Fecha Inicio no puede ser mayor que la Fecha Final");
                    return;
                }

                frappe.confirm(`¿Está seguro de generar el cierre del <b>${values.fecha_inicio}</b> al <b>${values.fecha_final}</b>?`, () => {
                    create_cierre(d, values);
                });
            }
        });

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
                    docstatus: 1 // Submit inmediato para aplicar cambios
                }
            },
            freeze: true,
            freeze_message: 'Procesando Cierre...',
            callback: function (r) {
                if (!r.exc) {
                    frappe.msgprint(`Cierre ${r.message.name} realizado correctamente.`);
                    dialog.hide();
                    refresh_dashboard();
                }
            }
        });
    }

    function format_currency(value, currency, decimals) {
        // Implementacion simple si frappe.format no esta disponible, pero frappe.format lo esta
        return frappe.format(value, { fieldtype: 'Currency', currency: currency || frappe.defaults.get_default("currency") });
    }

    // Init
    if (page.sucursal_field.get_value()) {
        refresh_dashboard();
    }
}
