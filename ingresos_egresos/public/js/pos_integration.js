frappe.provide("frappe.ie_pos");
frappe.ie_pos.install = function() {
        const proto = erpnext.PointOfSale.Controller.prototype;
        if (proto._ie_installed) return;
        proto._ie_installed = true;
        const api = this, prepare = proto.prepare_app_defaults, buttons=proto.prepare_btns,
            close=proto.close_pos, menu=proto.prepare_menu, listener=proto.setup_listener_for_pos_closing,
            outdated=proto.check_outdated_pos_opening_entry;
        proto.prepare_app_defaults = async function(data) {
            this.ie_context = await api.call("context",{opening:data.name});
            return prepare.call(this,data);
        };
        proto.prepare_btns = function() {
            buttons.call(this);
            if (!this.ie_context?.enabled) return;
            const opening=this.pos_opening, group=__("Ingresos y Egresos");
            this.page.add_inner_button(__("Registrar ingreso"),()=>api.movement(opening,"Ingreso"),group);
            this.page.add_inner_button(__("Registrar egreso"),()=>api.movement(opening,"Egreso"),group);
            this.page.add_inner_button(__("Movimientos y saldos"),()=>api.report(opening),group);
            if (this.ie_context.puede_cerrar) this.page.add_inner_button(__("Cierre conjunto"),()=>api.closing(opening,this),group);
            api.apply_state(this,this.ie_context.estado);
        };
        proto.prepare_menu = function() {
            if (!this.ie_context?.enabled) return menu.call(this);
            this.page.clear_menu();
            this.page.add_menu_item(__("Open Form View"),this.open_form_view.bind(this));
            if (this.ie_context.puede_cerrar) this.page.add_menu_item(__("Cierre conjunto"),()=>api.closing(this.pos_opening,this));
        };
        proto.close_pos = function() {return this.ie_context?.enabled ? api.closing(this.pos_opening,this) : close.call(this);};
        proto.check_outdated_pos_opening_entry = function() {
            // Integrated turns use their opening and exact timestamps, including overnight shifts.
            if (!this.ie_context?.enabled) return outdated.call(this);
        };
        proto.setup_listener_for_pos_closing = function() {
            if (!this.ie_context?.enabled) return listener.call(this);
            // Native 'Closed' is emitted even for queued ERP closings. Only our durable state means both are closed.
            this._ie_notify && frappe.realtime.off("ie_pos_turn",this._ie_notify);
            this._ie_notify = data => {
                if (data.opening !== this.pos_opening) return;
                api.apply_state(this,data.estado);
                frappe.show_alert({message: __("Turno POS") + ": " + data.estado,indicator:data.estado === "Error" ? "red" : "blue"});
            };
            frappe.realtime.on("ie_pos_turn",this._ie_notify);
        };
    };


(() => {
    const page = frappe.pages["point-of-sale"], original = page.on_page_load;
    page.on_page_load = async function(wrapper) {
        await frappe.require(["ie_assets.bundle.js", "ie_deferred.bundle.js", "ie_pos_modals.bundle.js"]);
        await frappe.require("point-of-sale.bundle.js");
        frappe.ie_pos.install();
        return original(wrapper);
    };
})();
