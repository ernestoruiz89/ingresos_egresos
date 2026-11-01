frappe.listview_settings["Movimiento"] = {
    add_fields: ["clasificacion", "moneda", "importe", "asiento_contable", "estado_contable", "origen_pos"],
    has_indicator_for_draft: true,
    get_indicator(doc) {
        if (doc.docstatus === 2) return [__("Anulado"), "red", "docstatus,=,2"];
        const state = ["Venta", "Devolucion"].includes(doc.origen_pos) ? "Gestionado por POS" : (doc.estado_contable || "Pendiente");
        const color = {Contabilizado: "green", "Asiento anulado": "orange", "Gestionado por POS": "blue"}[state] || "orange";
        return [__(state), color, "estado_contable,=," + state];
    },
    onload(listview) {
        if (frappe.model.can_create("Journal Entry") && frappe.model.can_submit("Journal Entry")) {
            listview.page.add_inner_button(__("Contabilizar seleccionados"), async () => {
                const names = listview.get_checked_items(true);
                if (!names.length) return frappe.msgprint(__("Seleccione al menos un movimiento."));
                await frappe.require("/assets/ingresos_egresos/js/ie_accounting.js");
                await frappe.ie_accounting.show(names, () => listview.refresh());
            });
        }
    },
    formatters: {
        importe(value, df, doc) {
            return frappe.format(value, {fieldtype: "Currency", options: "moneda"}, {only_value: true}, doc);
        }
    }
};
