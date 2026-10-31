/* Shared dialogs, bundled by Frappe so upgrades use versioned assets. */
frappe.provide("frappe.ie_pos");
Object.assign(frappe.ie_pos, {
    async call(method, args = {}) {
        const r = await frappe.call({method: "ingresos_egresos.pos." + method, args});
        return r.message;
    },
    esc(value) { return frappe.utils.escape_html(String(value ?? "")); },
    stamp(value) { return frappe.datetime.str_to_user(String(value || "").split(".")[0]); },
    money(value, currency) {
        return frappe.format(value, {fieldtype: "Currency", options: "moneda"}, {only_value: true}, {moneda: currency});
    },
    async movement(opening, tipo) {
        const ctx = await this.call("context", {opening});
        if (ctx.estado !== "Abierto") return frappe.msgprint(__("El turno está cerrado o en proceso de cierre."));
        const request_id = crypto.randomUUID ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,"0")).join("");
        const d = new frappe.ui.Dialog({title: __("Registrar") + " " + tipo, size: "large",
            fields: [
                {fieldtype: "Section Break", label: __("Datos del movimiento")},
                {fieldtype: "Select", fieldname: "clasificacion", label: __("Concepto"), options: ctx.conceptos[tipo], reqd: 1},
                {fieldtype: "Column Break"},
                {fieldtype: "Link", fieldname: "medio_pago", label: __("Medio de pago"), options: "Mode of Payment", reqd: 1,
                    get_query: () => ({filters: {name: ["in", ctx.medios_pago]}})},
                {fieldtype: "Section Break", label: __("Importe y moneda")},
                {fieldtype: "Float", fieldname: "importe", label: __("Importe"), reqd: 1, precision: 2},
                {fieldtype: "Float", fieldname: "tasa_de_cambio", label: __("Tasa a moneda base") + " (" + ctx.moneda_base + ")", precision: 9, reqd: 1},
                {fieldtype: "Column Break"},
                {fieldtype: "Link", fieldname: "moneda", label: __("Moneda"), options: "Currency", reqd: 1,
                    default: ctx.moneda_empresa, onchange: () => load_rates()},
                {fieldtype: "Float", fieldname: "tasa_empresa", label: __("Tasa a moneda de empresa") + " (" + ctx.moneda_empresa + ")", precision: 9,
                    hidden: ctx.moneda_base === ctx.moneda_empresa},
                ...frappe.ie_assets.fields(tipo),
                {fieldtype: "Section Break", label: __("Referencia y descripción")},
                {fieldtype: "Data", fieldname: "referencia", label: __("Referencia")},
                {fieldtype: "Column Break"},
                {fieldtype: "Small Text", fieldname: "descripcion", label: __("Descripción"), max_height: "90px"}
            ], primary_action_label: __("Registrar"),
            primary_action: async values => {
                d.get_primary_btn().prop("disabled", true);
                try {
                    await this.call("register_movement", {...values, opening, tipo, request_id});
                    d.hide(); frappe.show_alert({message: __("Movimiento registrado"), indicator: "green"});
                } finally { d.get_primary_btn().prop("disabled", false); }
            }
        });
        let sequence = 0;
        const load_rates = async () => {
            const seq = ++sequence, moneda = d.get_value("moneda");
            if (!moneda) return;
            await d.set_value("tasa_de_cambio", 0); await d.set_value("tasa_empresa", 0);
            d.set_df_property("tasa_de_cambio", "read_only", moneda === ctx.moneda_base ? 1 : 0);
            d.set_df_property("tasa_empresa", "read_only", moneda === ctx.moneda_empresa ? 1 : 0);
            const rates = await this.call("rates", {opening, moneda});
            if (seq !== sequence) return;
            if (!flt(d.get_value("tasa_de_cambio"))) await d.set_value("tasa_de_cambio", rates.tasa_de_cambio);
            if (!flt(d.get_value("tasa_empresa"))) await d.set_value("tasa_empresa", rates.tasa_empresa);
            if (!rates.tasa_de_cambio || !rates.tasa_empresa) frappe.show_alert({message: __("Complete la tasa de cambio manualmente."),indicator:"orange"});
        };
        frappe.ie_assets.bind(d);
        d.show(); await load_rates();
    },
    async report(opening) {
        const ctx = await this.call("context", {opening});
        let offset = 0, seq = 0;
        const d = new frappe.ui.Dialog({title: __("Movimientos y saldos del turno"), size: "extra-large",
            fields: [
                {fieldtype: "Link", fieldname: "moneda", label: __("Moneda"), options: "Currency", onchange: () => refresh(true)},
                {fieldtype: "Link", fieldname: "medio_pago", label: __("Medio de pago"), options: "Mode of Payment", onchange: () => refresh(true),
                    get_query: () => ({filters: {name: ["in",ctx.medios_pago]}})},
                {fieldtype: "HTML", fieldname: "resultados"}
            ], primary_action_label: __("Actualizar"), primary_action: () => refresh(false)
        });
        const refresh = async reset => {
            if (reset) offset = 0;
            const current = ++seq;
            const data = await this.call("report", {opening, moneda: d.get_value("moneda"), medio_pago: d.get_value("medio_pago"), start: offset});
            if (current !== seq) return;
            const cell = value => `<td>${this.esc(value)}</td>`;
            const amounts = (row, currency) => ["apertura","ventas","devoluciones","ingresos","egresos","saldo"].map(key => `<td class="text-right">${this.money(row[key],currency)}</td>`).join("");
            d.fields_dict.resultados.$wrapper.html(`
                <p>${this.esc(ctx.perfil)} · ${this.esc(ctx.sucursal)} · ${this.esc(data.estado)}</p>
                <p>${this.esc(this.stamp(data.inicio))} — ${this.esc(this.stamp(data.corte))} · ${this.esc(frappe.boot.time_zone.user)}</p>
                <div class="table-responsive"><table class="table table-bordered"><thead><tr>
                    <th>Moneda / Medio</th><th>Apertura</th><th>Ventas</th><th>Devoluciones</th><th>Ingresos manuales</th><th>Egresos manuales</th><th>Saldo esperado</th>
                </tr></thead><tbody>${data.por_medio_moneda.map(row => `<tr>${cell(row.moneda + " / " + row.medio_pago)}${amounts(row,row.moneda)}</tr>`).join("")}
                    <tr class="font-weight-bold">${cell("Consolidado " + data.moneda_base)}${amounts(data.base,data.moneda_base)}</tr></tbody></table></div>
                <div class="table-responsive"><table class="table table-striped"><thead><tr>
                    <th>Fecha y hora</th><th>Tipo</th><th>Concepto</th><th>Origen</th><th>Medio</th><th>Importe</th><th>Referencia</th>
                </tr></thead><tbody>${data.movimientos.map(row => `<tr>${cell(this.stamp(row.fecha_operacion))}${cell(row.tipo)}${cell(row.clasificacion)}${cell(row.origen_pos)}${cell(row.medio_pago)}<td>${this.money(row.importe,row.moneda)}</td>${cell(row.referencia)}</tr>`).join("") || '<tr><td colspan="7">Sin movimientos</td></tr>'}</tbody></table></div>
                <div class="flex justify-between"><button class="btn btn-default ie-prev" ${offset === 0 ? "disabled" : ""}>Anterior</button>
                    <span>${data.total ? offset + 1 : 0}–${Math.min(offset+25,data.total)} / ${data.total}</span>
                    <button class="btn btn-default ie-next" ${offset + 25 >= data.total ? "disabled" : ""}>Siguiente</button></div>`);
            d.fields_dict.resultados.$wrapper.find(".ie-prev").on("click", () => {offset = Math.max(0,offset-25);refresh(false);});
            d.fields_dict.resultados.$wrapper.find(".ie-next").on("click", () => {offset += 25;refresh(false);});
        };
        d.show(); await refresh(false);
    },
    async closing(opening, controller = null) {
        const ctx = await this.call("context", {opening});
        const data = await this.call("report", {opening});
        let timer, busy = false, hidden = false;
        const d = new frappe.ui.Dialog({title: __("Cierre conjunto POS / Ingresos y Egresos"), size: "large",
            fields: [
                {fieldtype: "HTML", fieldname: "estado"},
                {fieldtype: "Table", fieldname: "arqueo", label: __("Arqueo en") + " " + ctx.moneda_empresa, cannot_add_rows: true, cannot_delete_rows: true,
                    data: Object.entries(data.esperado_empresa).map(([medio_pago, esperado]) => ({medio_pago, esperado, contado: esperado})),
                    fields: [
                        {fieldtype: "Data", fieldname: "medio_pago", label: __("Medio de pago"), in_list_view: 1, read_only: 1},
                        {fieldtype: "Float", fieldname: "esperado", label: __("Esperado"), precision: 2, in_list_view: 1, read_only: 1},
                        {fieldtype: "Float", fieldname: "contado", label: __("Contado"), precision: 2, in_list_view: 1}
                    ]},
                {fieldtype: "Check", fieldname: "confirmar", label: __("He verificado los importes contados")}
            ], primary_action_label: __("Cerrar ambos sistemas"),
            primary_action: async () => {
                if (busy) return;
                busy = true; d.get_primary_btn().prop("disabled",true);
                try {
                    const state = await this.call("status", {opening});
                    if (state.estado === "Cerrado") {
                        d.hide(); if (controller) window.location.reload(); return;
                    }
                    if (state.estado === "Abierto") {
                        if (!d.get_value("confirmar")) {frappe.msgprint(__("Verifique y confirme los importes contados.")); return;}
                        const counted = Object.fromEntries(d.get_value("arqueo").map(row => [row.medio_pago,row.contado]));
                        await this.call("start_closing", {opening,counted});
                    } else await this.call("retry", {opening});
                    await refresh();
                } finally {busy=false;d.get_primary_btn().prop("disabled",false);}
            }, onhide: () => {hidden=true;clearInterval(timer);}
        });
        const refresh = async () => {
            const state = await this.call("status", {opening});
            if (hidden) return;
            d.fields_dict.estado.$wrapper.html(`<p><strong>${this.esc(state.estado)}</strong>${state.erp_estado ? ' · ERPNext: '+this.esc(__(state.erp_estado)) : ''}</p>${state.error || state.erp_error ? `<p class="text-danger">${this.esc(state.error || state.erp_error)}</p>` : ""}<p class="text-muted">La siguiente apertura se habilita cuando ambos cierres terminan. Puede cerrar esta ventana: el proceso continúa en el servidor.</p>`);
            const open = state.estado === "Abierto";
            d.set_df_property("arqueo","hidden",open ? 0 : 1);d.set_df_property("confirmar","hidden",open ? 0 : 1);
            d.get_primary_btn().text(state.estado === "Cerrado" ? __("Finalizar") : open ? __("Cerrar ambos sistemas") : __("Reintentar / Actualizar"));
            if (controller) this.apply_state(controller,state.estado);
            if (["Cerrado","Abierto","Cancelado"].includes(state.estado)) {clearInterval(timer);timer=null;}
            else if (!timer) timer=setInterval(() => {if (!busy) refresh().catch(()=>{clearInterval(timer);timer=null;});},3000);
        };
        d.show(); await refresh();
    },
    apply_state(controller, state) {
        controller.ie_state = state;
        if (controller.$components_wrapper) controller.$components_wrapper.prop("inert",state !== "Abierto");
    }
});
