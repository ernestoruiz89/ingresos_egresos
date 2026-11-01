/* Shared, reviewed posting flow for the document and selected list rows. */
frappe.provide("frappe.ie_accounting");
Object.assign(frappe.ie_accounting, {
    esc(value) { return frappe.utils.escape_html(String(value ?? "")); },
    async call(method, args) {
        return (await frappe.call({method: "ingresos_egresos.accounting." + method, args})).message;
    },
    async show(names, on_posted) {
        if (!names.length) return frappe.msgprint(__("Seleccione al menos un movimiento."));
        const rows = await this.call("get_preview", {names});
        return this.editor(rows, on_posted);
    },
    async editor(rows, on_posted, completing = false) {
        const active = rows.filter(row => row.eligible);
        const skipped = rows.filter(row => !row.eligible);
        const labels = {cuenta_contrapartida: __("Cuenta"), centro_de_costos: __("Centro de costos"),
            party_type: __("Tipo de tercero"), party: __("Tercero"), tasa_empresa: __("Tasa contable"), cuenta_diferida: __("Cuenta diferida")};
        const summary = `<p>${__("Se generará un asiento por movimiento, con la fecha y los importes guardados.")}</p>` +
            active.filter(row => row.faltantes?.length).map(row => `<div class="alert alert-info">${this.esc(row.name)}: ${row.faltantes.map(field => this.esc(labels[field] || field)).join(", ")}</div>`).join("") +
            active.filter(row => row.es_activo).map(row => `<p><strong>${__("Activo fijo")}: ${this.esc(row.nombre_activo)}</strong><br>${__("Se creará su ficha; las cuentas se toman de su categoría.")}</p>`).join("") +
            active.filter(row => row.es_diferido).map(row => `<p><strong>${this.esc(row.name)} · ${__("Diferimiento mensual")}</strong><br>${this.esc(row.meses_diferimiento)} ${__("meses desde")} ${this.esc(row.inicio_diferimiento)}. ${__("El asiento inicial usa la cuenta diferida; las cuotas reconocerán el ingreso o gasto.")}</p>`).join("") +
            (skipped.length ? `<div class="text-muted">${skipped.map(row => this.esc(row.name) + ": " + this.esc(row.motivo)).join("<br>")}</div>` : "");
        if (!active.length) return frappe.msgprint({title: __("Contabilización"), message: summary});
        let dialog, busy = false, requirements_sequence = 0;
        const single = active.length === 1, row = active[0];
        const account_query = doc => doc.es_activo ? {filters: {company: doc.company, root_type: "Asset", is_group: 0, disabled: 0}} :
            {query: "ingresos_egresos.accounting.account_query", filters: {company: doc.company, tipo: doc.tipo, es_diferido: doc.es_diferido ? 1 : 0}};
        const deferred_query = doc => ({filters: {company: doc.company, root_type: doc.tipo === "Ingreso" ? "Liability" : "Asset",
            report_type: "Balance Sheet", account_currency: doc.moneda_empresa, is_group: 0, disabled: 0,
            account_type: ["not in", ["Cash", "Bank", "Receivable", "Payable", "Fixed Asset", "Stock", "Accumulated Depreciation"]]}});
        const fields = [{fieldtype: "HTML", fieldname: "resumen", options: summary}];
        if (single) {
            fields.push(
                {fieldtype: "Section Break", label: row.name},
                {fieldtype: "Link", fieldname: "company", label: __("Empresa"), options: "Company", default: row.company, read_only: 1},
                {fieldtype: "Link", fieldname: "cuenta_caja", label: __("Cuenta de caja"), options: "Account", default: row.cuenta_caja, read_only: 1},
                {fieldtype: "Column Break"},
                {fieldtype: "Currency", fieldname: "importe", label: __("Importe") + " (" + row.moneda + ")", default: row.importe, options: row.moneda, read_only: 1},
                {fieldtype: "Float", fieldname: "tasa_empresa", label: __("Tasa contable a") + " " + row.moneda_empresa,
                    precision: 9, default: row.tasa_empresa, reqd: 1, read_only: !row.tasa_editable},
                {fieldtype: "Section Break", label: __("Contrapartida y datos obligatorios")},
                {fieldtype: "Link", fieldname: "cuenta_contrapartida", label: row.es_activo ? __("Cuenta del activo") : row.es_diferido ? __("Cuenta a reconocer") : __("Cuenta contrapartida"), options: "Account",
                    default: row.cuenta_contrapartida, read_only: row.es_activo ? 1 : 0, reqd: 1, get_query: () => account_query(row),
                    onchange: () => {if (dialog) refresh_requirements(true);}},
                {fieldtype: "Link", fieldname: "centro_de_costos", label: __("Centro de costos"), options: "Cost Center", default: row.centro_de_costos,
                    get_query: () => ({filters: {company: row.company, is_group: 0, disabled: 0}})},
                {fieldtype: "Column Break"},
                ...(row.es_diferido ? [{fieldtype: "Link", fieldname: "cuenta_diferida", label: __("Cuenta diferida"), options: "Account", default: row.cuenta_diferida,
                    reqd: 1, get_query: () => deferred_query(row)}] : []),
                {fieldtype: "Link", fieldname: "party_type", label: __("Tipo de tercero"), options: "Party Type", default: row.party_type,
                    hidden: !row.requiere_tercero,
                    get_query: () => ({filters: {name: ["in", row.tipos_tercero || []]}}), onchange: () => {if (dialog) dialog.set_value("party", "");}},
                {fieldtype: "Dynamic Link", fieldname: "party", label: __("Tercero"), options: "party_type", default: row.party, hidden: !row.requiere_tercero}
            );
        } else {
            fields.push({fieldtype: "Table", fieldname: "detalles", label: __("Revise cada movimiento; abra la fila para completar tercero y centro de costos."),
                cannot_add_rows: true, cannot_delete_rows: true,
                data: active.map(item => ({...item, movimiento: item.name, modificado: item.modified})),
                fields: [
                    {fieldtype: "Link", fieldname: "movimiento", label: __("Movimiento"), options: "Movimiento", in_list_view: 1, read_only: 1, columns: 3},
                    {fieldtype: "Link", fieldname: "company", label: __("Empresa"), options: "Company", read_only: 1},
                    {fieldtype: "Link", fieldname: "cuenta_caja", label: __("Cuenta de caja"), options: "Account", read_only: 1},
                    {fieldtype: "Column Break"},
                    {fieldtype: "Data", fieldname: "moneda", label: __("Moneda"), in_list_view: 1, read_only: 1, columns: 1},
                    {fieldtype: "Float", fieldname: "importe", label: __("Importe"), in_list_view: 1, read_only: 1, columns: 2},
                    {fieldtype: "Data", fieldname: "moneda_empresa", label: __("Moneda de empresa"), read_only: 1},
                    {fieldtype: "Section Break", label: __("Datos para contabilizar")},
                    {fieldtype: "Link", fieldname: "cuenta_contrapartida", label: __("Contrapartida"), options: "Account", in_list_view: 1, columns: 3,
                        get_query: account_query, read_only_depends_on: "eval:doc.es_activo"},
                    {fieldtype: "Link", fieldname: "centro_de_costos", label: __("Centro de costos"), options: "Cost Center", get_query: doc => ({filters: {company: doc.company, is_group: 0, disabled: 0}})},
                    {fieldtype: "Link", fieldname: "cuenta_diferida", label: __("Cuenta diferida"), options: "Account", get_query: deferred_query, depends_on: "es_diferido"},
                    {fieldtype: "Column Break"},
                    {fieldtype: "Link", fieldname: "party_type", label: __("Tipo de tercero"), options: "Party Type"},
                    {fieldtype: "Dynamic Link", fieldname: "party", label: __("Tercero"), options: "party_type"},
                    {fieldtype: "Float", fieldname: "tasa_empresa", label: __("Tasa contable"), precision: 9, in_list_view: 1, columns: 1,
                        read_only_depends_on: "eval:!doc.tasa_editable"},
                    {fieldtype: "Check", fieldname: "tasa_editable", hidden: 1},
                    {fieldtype: "Check", fieldname: "es_activo", hidden: 1},
                    {fieldtype: "Check", fieldname: "es_diferido", hidden: 1},
                    {fieldtype: "Data", fieldname: "tipo", hidden: 1},
                    {fieldtype: "Data", fieldname: "modificado", hidden: 1}
                ]});
        }
        fields.push({fieldtype: "Section Break"}, {fieldtype: "Check", fieldname: "confirmar", label: __("He revisado los datos para contabilizar")});
        const refresh_requirements = async changed_account => {
            if (!single || !dialog.get_value("cuenta_contrapartida")) return;
            const sequence = ++requirements_sequence;
            if (changed_account) {await dialog.set_value("party_type", ""); await dialog.set_value("party", "");}
            const values = dialog.get_values(true);
            const updated = await this.call("get_requirements", {name: row.name, cuenta_contrapartida: values.cuenta_contrapartida,
                centro_de_costos: values.centro_de_costos, party_type: values.party_type, party: values.party, tasa_empresa: values.tasa_empresa, cuenta_diferida: values.cuenta_diferida});
            if (sequence !== requirements_sequence) return;
            row.tipos_tercero = updated.tipos_tercero || [];
            dialog.set_df_property("centro_de_costos", "reqd", updated.requiere_centro ? 1 : 0);
            for (const field of ["party_type", "party"]) {
                dialog.set_df_property(field, "reqd", updated.requiere_tercero ? 1 : 0);
                dialog.set_df_property(field, "hidden", updated.requiere_tercero ? 0 : 1);
            }
            if (!dialog.get_value("party_type") && updated.party_type) await dialog.set_value("party_type", updated.party_type);
        };
        dialog = new frappe.ui.Dialog({title: completing ? __("Completar datos antes de contabilizar") : __("Contabilizar movimientos"),
            size: single ? "large" : "extra-large", fields,
            primary_action_label: __("Contabilizar") + " " + active.length,
            primary_action: async values => {
                if (busy) return;
                if (!values.confirmar) return frappe.msgprint(__("Revise los datos y marque la confirmación antes de contabilizar."));
                const entries = single ? [{name: row.name, modified: row.modified, ...values}] : values.detalles.map(item => ({
                    name: item.movimiento, modified: item.modificado, cuenta_contrapartida: item.cuenta_contrapartida,
                    centro_de_costos: item.centro_de_costos, party_type: item.party_type, party: item.party, tasa_empresa: item.tasa_empresa, cuenta_diferida: item.cuenta_diferida
                }));
                busy = true; dialog.get_primary_btn().prop("disabled", true);
                try {
                    const result = await this.call("post_movements", {entries});
                    if (result.status === "needs_input") {
                        dialog.hide();
                        return this.editor(result.rows, on_posted, true);
                    }
                    dialog.hide();
                    await on_posted?.();
                    frappe.msgprint({title: __("Resultado de contabilización"), indicator: "green",
                        message: result.results.map(item => `${this.esc(item.name)}: ${this.esc(item.resultado)} ${item.asiento_contable ?
                            `<a href="/app/journal-entry/${encodeURIComponent(item.asiento_contable)}">${this.esc(item.asiento_contable)}</a>` : ""}${item.activo_fijo ?
                            ` · <a href="/app/asset/${encodeURIComponent(item.activo_fijo)}">${this.esc(item.activo_fijo)}</a>` : ""}${item.diferimiento ?
                            ` · <a href="/app/ie-diferimiento/${encodeURIComponent(item.diferimiento)}">${this.esc(item.diferimiento)}</a>` : ""}`).join("<br>")});
                } finally {busy = false; dialog.get_primary_btn().prop("disabled", false);}
            }
        });
        dialog.show();
        if (single) await refresh_requirements(false);
    }
});
