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
    },
    refresh: ie_currency_configuration,
    permitir_multimoneda: ie_currency_configuration,
    after_save() {frappe.ie_currency._settings?.clear?.();}
});

function ie_currency_configuration(frm) {
    const readonly = !Number(frm.doc.permitir_multimoneda);
    frm.set_df_property("moneda_base","read_only",readonly ? 1 : 0);
    frm.fields_dict.cuentas_caja.grid.update_docfield_property("moneda","read_only",readonly ? 1 : 0);
}

frappe.ui.form.on("IE Cuenta Caja", {
    async company(frm, cdt, cdn) {
        frappe.model.set_value(cdt, cdn, "cuenta_caja", "");
        frappe.model.set_value(cdt, cdn, "centro_de_costos", "");
        const row = locals[cdt][cdn];
        if (Number(frm.doc.permitir_multimoneda) || !row.__islocal || !row.company) return;
        const company = row.company;
        const response = await frappe.db.get_value("Company",company,"default_currency");
        if (row.company === company && !Number(frm.doc.permitir_multimoneda))
            return frappe.model.set_value(cdt,cdn,"moneda",response.message.default_currency);
    },
    moneda(_frm, cdt, cdn) {frappe.model.set_value(cdt, cdn, "cuenta_caja", "");}
});
