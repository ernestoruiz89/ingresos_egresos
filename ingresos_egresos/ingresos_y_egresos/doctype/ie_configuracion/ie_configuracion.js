// Copyright (c) 2024, Ernesto Ruiz and contributors
// For license information, please see license.txt

frappe.ui.form.on("IE Configuracion", {
    setup(frm) {
        frm.set_query("cuenta_caja", "cuentas_caja", (_doc, cdt, cdn) => {
            const row = locals[cdt][cdn];
            return {filters: {company: row.company, account_currency: row.moneda, is_group: 0, disabled: 0,
                account_type: ["in", ["Cash", "Bank"]]}};
        });
        frm.set_query("centro_de_costos", "cuentas_caja", (_doc, cdt, cdn) => ({
            filters: {company: locals[cdt][cdn].company, is_group: 0, disabled: 0}
        }));
    }
});

frappe.ui.form.on("IE Cuenta Caja", {
    company(_frm, cdt, cdn) {
        frappe.model.set_value(cdt, cdn, "cuenta_caja", "");
        frappe.model.set_value(cdt, cdn, "centro_de_costos", "");
    },
    moneda(_frm, cdt, cdn) {frappe.model.set_value(cdt, cdn, "cuenta_caja", "");}
});
