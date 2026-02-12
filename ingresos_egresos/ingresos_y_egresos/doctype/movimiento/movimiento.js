// Copyright (c) 2024, Ernesto Ruiz and contributors
// For license information, please see license.txt

frappe.ui.form.on('Movimiento', {
    onload: function (frm) {
        if (frm.doc.docstatus === 1) return;
        get_code_name_options(frm, frm.doc.tipo);
    },
    refresh: function (frm) {
        if (frm.doc.docstatus === 0) {
            // Asegurarnos de que el botón principal sea siempre "Guardar" y no "Enviar" (Submit)
            // Ya que el envío se hace masivamente desde el doctype "Cierre de Movimiento"
            frm.page.set_primary_action(__('Save'), () => frm.save());

            if (!frm.is_new()) {
                // Agregar botón de eliminar en rojo para movimientos no vinculados
                if (!frm.doc.vinculado) {
                    frm.page.add_inner_button(__('Eliminar Registro'), function () {
                        frappe.confirm('¿Está seguro de que desea eliminar este registro?', () => {
                            frappe.call({
                                method: 'frappe.client.delete',
                                args: {
                                    doctype: 'Movimiento',
                                    name: frm.doc.name
                                },
                                callback: function (r) {
                                    if (!r.exc) {
                                        frappe.show_alert({ message: __('Registro eliminado'), indicator: 'green' });
                                        frappe.set_route('List', 'Movimiento');
                                    }
                                }
                            });
                        });
                    }).addClass('btn-danger').css({ 'color': 'white', 'font-weight': 'bold' });
                }

                frm.set_intro(__('Este movimiento debe ser procesado mediante un <a href="/app/List/Registro%20de%20Cierre%20de%20Movimiento" style="font-weight:bold">Cierre de Movimientos</a> para ser finalizado.'), 'blue');
            }
        }
    },
    tipo: function (frm) {
        if (frm.doc.docstatus === 1) return;
        get_code_name_options(frm, frm.doc.tipo);
    }
});

function get_code_name_options(frm, code_name) {
    if (frm.doc.docstatus === 1) return;

    // Si no hay tipo seleccionado, limpiar opciones
    if (!code_name) {
        frm.set_df_property('clasificacion', 'options', []);
        return;
    }

    frappe.call({
        method: 'ingresos_egresos.ingresos_y_egresos.doctype.movimiento.movimiento.get_code_name_options',
        args: {
            code_name: code_name
        },
        callback: function (response) {
            if (response.message) {
                // Establecer las opciones en el campo 'clasificacion'
                let options = response.message;
                // Add empty option at start if needed or just set existing
                frm.set_df_property('clasificacion', 'options', options);

                // Si el valor actual no está en las opciones, limpiar
                if (frm.doc.clasificacion && !options.includes(frm.doc.clasificacion)) {
                    frm.set_value('clasificacion', '');
                }
                // Opcional: Seleccionar la primera si no hay valor
                // else if (!frm.doc.clasificacion && options.length > 0) {
                //    frm.set_value('clasificacion', options[0]);
                // }
            } else {
                frm.set_df_property('clasificacion', 'options', []);
            }
        }
    });
}
