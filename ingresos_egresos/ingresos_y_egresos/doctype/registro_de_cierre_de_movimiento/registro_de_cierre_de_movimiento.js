frappe.ui.form.on("Registro de Cierre de Movimiento", {
	setup: function(frm){
		frm.ignore_doctypes_on_cancel_all = ["Movimiento"];
	},
	
	onload: function (frm) {
        if (!frm.doc.__islocal) return;		

        // Obtener el último cierre registrado para la sucursal seleccionada
        if (frm.doc.sucursal) {
            frappe.call({
                method: "frappe.client.get_list",
                args: {
                    doctype: "Registro de Cierre de Movimiento",
                    filters: { sucursal: frm.doc.sucursal, docstatus: 1 },
                    fields: ["fecha_inicio", "fecha_final"],
                    order_by: "fecha_final desc",
                    limit_page_length: 1
                },
                callback: function (r) {
                    if (r.message && r.message.length > 0) {
                        let ultimo_cierre = r.message[0];
                        let nueva_fecha_inicio = frappe.datetime.add_days(ultimo_cierre.fecha_final, 1);
                        frm.set_value("fecha_inicio", nueva_fecha_inicio);
                    }
                }
            });
        }
    },
    sucursal: function (frm) {
        // Volver a calcular la fecha inicial si cambia la sucursal
        frm.trigger("onload");
    },
	
    actualizar_movimientos: function (frm) {
        if (!frm.doc.sucursal) {
            frappe.msgprint("Por favor, seleccione una sucursal antes de actualizar los movimientos.");
            return;
        }
        if (!frm.doc.fecha_inicio || !frm.doc.fecha_final) {
            frappe.msgprint("Por favor, seleccione un rango de fechas válido.");
            return;
        }

        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "Movimiento",
                filters: {
                    sucursal: frm.doc.sucursal,
                    fecha_de_registro: ["between", [frm.doc.fecha_inicio, frm.doc.fecha_final]],
                    docstatus: 1 // Solo movimientos aplicados
                },
                fields: ["name", "tipo", "clasificacion", "fecha_de_registro", "importe", "descripcion"]
            },
            callback: function (r) {
                if (r.message) {
                    console.log("Movimientos obtenidos:", r.message);

                    // Separar ingresos y egresos
                    let ingresos = r.message.filter(m => m.tipo === "Ingreso");
                    let egresos = r.message.filter(m => m.tipo === "Egreso");

                    // Limpiar tablas
                    frm.clear_table("ingresos");
                    frm.clear_table("egresos");

                    // Llenar tabla de ingresos
                    ingresos.forEach(m => {
                        let row = frm.add_child("ingresos");
                        row.registro = m.name; // Campo Movimiento
                        row.clasificación = m.clasificacion; // Campo Clasificación
                        row.fecha = m.fecha_de_registro; // Campo Fecha
                        row.importe = m.importe; // Campo Importe
                        row.descripcion = m.descripcion; // Campo Descripción
                    });

                    // Llenar tabla de egresos
                    egresos.forEach(m => {
                        let row = frm.add_child("egresos");
                        row.registro = m.name; // Campo Movimiento
                        row.clasificación = m.clasificacion; // Campo Clasificación
                        row.fecha = m.fecha_de_registro; // Campo Fecha
                        row.importe = m.importe; // Campo Importe
                        row.descripcion = m.descripcion; // Campo Descripción
                    });

                    // Calcular totales
                    let total_ingresos = ingresos.reduce((sum, m) => sum + m.importe, 0);
                    let total_egresos = egresos.reduce((sum, m) => sum + m.importe, 0);

                    // Actualizar totales
                    frm.set_value("total_ingresos", total_ingresos);
                    frm.set_value("total_egresos", total_egresos);

                    // Refrescar campos
                    frm.refresh_field("ingresos");
                    frm.refresh_field("egresos");

                    frappe.msgprint("Movimientos actualizados correctamente.");
                } else {
                    frappe.msgprint("No se encontraron movimientos en el rango especificado.");
                }
            }
        });
    }
});
