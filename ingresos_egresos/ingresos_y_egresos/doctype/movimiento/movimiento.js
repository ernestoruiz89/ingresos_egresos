// Copyright (c) 2024, Ernesto Ruiz and contributors
// For license information, please see license.txt

frappe.ui.form.on('Movimiento', {
    onload: function (frm) {
        if (frm.doc.docstatus === 1) return;
        get_code_name_options(frm, frm.doc.tipo);
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
