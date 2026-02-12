frappe.pages['dashboard-movimientos'].on_page_load = function (wrapper) {
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
            refresh_dashboard(true);
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
            .dashboard-card-bg {
                margin-bottom: 15px;
                transition: transform 0.2s;
            }
            .dashboard-card-bg:hover {
                transform: translateY(-2px);
            }
            .quick-actions-container .btn {
                margin-bottom: 5px;
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
                .dashboard-card-bg h2 {
                    font-size: 1.6rem !important;
                }
                .dashboard-card-bg h5 {
                    font-size: 0.9rem !important;
                }
                /* Ocultar columnas menos importantes en móvil */
                .hidden-xs {
                    display: none !important;
                }
            }
        </style>
		<div class="dashboard-container" style="padding: 20px;">
			<!-- Sección de Tarjetas KPI -->
			<div class="row">
				<div class="col-sm-6 col-md-3">
					<div class="dashboard-card-bg" style="background: #e2e3e5; padding: 20px; border-radius: 8px; border: 1px solid #d6d8db;">
						<h5 style="color: #383d41;">Saldo Anterior</h5>
						<h2 id="kpi-saldo-anterior" style="font-weight: bold; margin-top: 10px;">$ 0.00</h2>
						<div style="font-size: 11px; visibility: hidden;">&nbsp;</div>
					</div>
				</div>
                <div class="col-sm-6 col-md-3">
					<div class="dashboard-card-bg" style="background: #d4edda; padding: 20px; border-radius: 8px; border: 1px solid #c3e6cb;">
						<h5 style="color: #155724;">Total Ingresos</h5>
						<h2 id="kpi-ingresos" style="font-weight: bold; margin-top: 10px;">$ 0.00</h2>
						<div id="kpi-ingresos-detail" style="font-size: 11px; color: #155724; opacity: 0.8;"></div>
					</div>
				</div>
				<div class="col-sm-6 col-md-3">
					<div class="dashboard-card-bg" style="background: #f8d7da; padding: 20px; border-radius: 8px; border: 1px solid #f5c6cb;">
						<h5 style="color: #721c24;">Total Egresos</h5>
						<h2 id="kpi-egresos" style="font-weight: bold; margin-top: 10px;">$ 0.00</h2>
						<div id="kpi-egresos-detail" style="font-size: 11px; color: #721c24; opacity: 0.8;"></div>
					</div>
				</div>
				<div class="col-sm-6 col-md-3">
					<div class="dashboard-card-bg" style="background: #cce5ff; padding: 20px; border-radius: 8px; border: 1px solid #b8daff;">
						<h5 style="color: #004085;">Saldo Actual</h5>
						<h2 id="kpi-saldo" style="font-weight: bold; margin-top: 10px;">$ 0.00</h2>
						<div style="font-size: 11px; visibility: hidden;">&nbsp;</div>
					</div>
				</div>
			</div>

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
									<th>Monto</th>
									<th>Estado</th>
                                    <th>Acciones</th>
								</tr>
							</thead>
							<tbody>
								<tr><td colspan="7" class="text-center">Seleccione una sucursal para ver datos</td></tr>
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

    function refresh_dashboard(is_sucursal_change = false) {
        let sucursal = page.sucursal_field.get_value();
        let from_date = page.desde_field.get_value();
        let to_date = page.hasta_field.get_value();

        // Guardar persistencia de filtros
        if (sucursal) {
            localStorage.setItem('dashboard_movimientos_filters', JSON.stringify({
                sucursal: sucursal,
                from_date: from_date,
                to_date: to_date
            }));
        }

        if (!sucursal) {
            $('#kpi-ingresos').html(format_currency(0));
            $('#kpi-egresos').html(format_currency(0));
            $('#kpi-saldo-anterior').html(format_currency(0));
            $('#kpi-saldo').html(format_currency(0));
            $('#table-movimientos tbody').html('<tr><td colspan="7" class="text-center">Seleccione una sucursal para ver datos</td></tr>');
            return;
        }

        frappe.call({
            method: "ingresos_egresos.ingresos_y_egresos.page.dashboard_movimientos.dashboard_movimientos.get_dashboard_data",
            args: {
                sucursal: sucursal,
                from_date: from_date,
                to_date: to_date
            },
            callback: function (r) {
                if (r.message) {
                    // Si cambió la sucursal, actualizamos el filtro 'Desde' sugerido
                    if (is_sucursal_change && r.message.periodo && r.message.periodo.ultimo_cierre) {
                        let next_day = frappe.datetime.add_days(r.message.periodo.ultimo_cierre, 1);
                        // Usamos set_input para evitar disparar el evento 'change' inmediatamente si es posible
                        // o manejamos la recursión indirectamente. 
                        // En Frappe, set_value/set_input suele disparar el evento.
                        page.desde_field.set_input(next_day);
                        // Actualizamos de nuevo con la nueva fecha para obtener datos filtrados
                        refresh_dashboard();
                        return;
                    }

                    update_kpis(r.message.totales);
                    update_table(r.message.movimientos);
                }
            }
        });
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
            tbody.append('<tr><td colspan="7" class="text-center">No hay movimientos recientes</td></tr>');
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
				<td class="text-right font-weight-bold">${format_currency(mov.importe)}</td>
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
                            reqd: 1
                        },
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
                    ],
                    primary_action_label: 'Registrar',
                    primary_action: function (values) {
                        values.tipo = tipo;
                        create_movimiento(d, values);
                    }
                });

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
            // Obtener opciones de clasificación
            frappe.call({
                method: 'ingresos_egresos.ingresos_y_egresos.doctype.movimiento.movimiento.get_code_name_options',
                args: { code_name: doc.tipo },
                callback: function (r_opts) {
                    page.opening_dialog = false;
                    let clasif_options = r_opts.message || [];

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
                                    fieldtype: 'Currency',
                                    default: doc.importe,
                                    reqd: 1,
                                    read_only: read_only
                                },
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
                                fields: fields,
                                primary_action_label: read_only ? null : 'Guardar Cambios',
                                secondary_action_label: read_only ? null : 'Eliminar Registro',
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

        page.opening_dialog = true;
        frappe.call({
            method: 'frappe.client.get_value',
            args: {
                doctype: 'Registro de Cierre de Movimiento',
                filters: { sucursal: sucursal, docstatus: 1 },
                fieldname: 'fecha_final',
                order_by: 'fecha_final desc'
            },
            callback: function (r_cierre) {
                let suggested_start_date = frappe.datetime.get_today();

                if (r_cierre.message && r_cierre.message.fecha_final) {
                    // Caso 1: Hay un cierre previo -> Fecha Inicio = Cierre Previo + 1 día
                    suggested_start_date = frappe.datetime.add_days(r_cierre.message.fecha_final, 1);
                    page.opening_dialog = false;
                    show_cierre_dialog(sucursal, suggested_start_date);
                } else {
                    // Caso 2: No hay cierre previo -> Buscar el movimiento abierto más antiguo
                    frappe.call({
                        method: 'frappe.client.get_value',
                        args: {
                            doctype: 'Movimiento',
                            filters: { sucursal: sucursal, vinculado: 0, docstatus: ['<', 2] },
                            fieldname: 'fecha_de_registro',
                            order_by: 'fecha_de_registro asc'
                        },
                        callback: function (r_mov) {
                            page.opening_dialog = false;
                            if (r_mov.message && r_mov.message.fecha_de_registro) {
                                suggested_start_date = r_mov.message.fecha_de_registro;
                            }
                            show_cierre_dialog(sucursal, suggested_start_date);
                        }
                    });
                }
            }
        });
    }

    function show_cierre_dialog(sucursal, start_date) {
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
                    default: start_date,
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
