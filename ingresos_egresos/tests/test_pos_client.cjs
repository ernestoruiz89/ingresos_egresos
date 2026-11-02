const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup(enabled) {
    const events = {}, calls = [], actions = [];
    class Controller {
        prepare_app_defaults(data) {this.pos_opening=data.name;calls.push('defaults');}
        prepare_btns() {calls.push('buttons');}
        prepare_menu() {calls.push('menu');}
        close_pos() {calls.push('native-close');}
        setup_listener_for_pos_closing() {events.native=true;}
        check_outdated_pos_opening_entry() {calls.push('outdated');}
        create_opening_voucher() {calls.push('native-opening');}
        new_invoice_event() {calls.push('new-invoice');}
        open_form_view() {}
    }
    const frappe = {ie_pos:{},provide(){},utils:{},pages:{'point-of-sale':{
        on_page_load:()=>calls.push('page')
    }},require:async name=>calls.push(name),realtime:{
        on:(name,handler)=>events[name]=handler,off:name=>delete events[name]
    },show_alert:()=>calls.push('alert')};
    const sandbox={frappe,erpnext:{PointOfSale:{Controller}},__:v=>v};
    for (const name of ['ie_pos_modals.js','pos_integration.js'])
        vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/js',name),'utf8'),sandbox);
    frappe.ie_pos.call=async()=>({enabled,estado:'Abierto',puede_cerrar:true});
    frappe.ie_pos.closing=()=>calls.push('joint-close');
    frappe.ie_pos.movement=(_,kind)=>calls.push(kind);
    frappe.ie_pos.report=()=>calls.push('report');
    frappe.ie_pos.install();
    const controller=new Controller();
    controller.page={add_inner_button:(label,action,group)=>actions.push({label,action,group}),
        set_primary_action:(label,action)=>controller.primary={label,action},
        clear_menu(){},add_menu_item(){}};
    controller.$components_wrapper={prop:(key,value)=>controller[key]=value};
    return {controller,frappe,events,calls,actions};
}

test('disabled integration preserves native buttons, menu, listener and closing',async()=>{
    const {controller,calls,actions,events}=setup(false);
    await controller.prepare_app_defaults({name:'opening'});
    controller.prepare_btns();controller.prepare_menu();controller.setup_listener_for_pos_closing();controller.close_pos();
    assert.equal(actions.length,0);
    assert.equal(events.native,true);
    assert.ok(calls.includes('menu')&&calls.includes('native-close'));
});

test('four POS actions operate in modals and replace native closing',async()=>{
    const {controller,calls,actions}=setup(true);
    await controller.prepare_app_defaults({name:'opening'});
    controller.prepare_btns();controller.close_pos();
    assert.deepEqual(actions.map(a=>a.label),['Registrar ingreso','Registrar egreso','Movimientos y saldos','Cierre conjunto']);
    assert.equal(actions.at(-1).group,undefined,'joint closing is visible outside the dropdown');
    actions.forEach(a=>a.action());
    assert.ok(calls.includes('Ingreso')&&calls.includes('Egreso')&&calls.includes('report'));
    assert.equal(calls.filter(v=>v==='joint-close').length,2);
    assert.ok(!calls.includes('native-close'));
});

test('a closed turn has a primary recovery action and reopening restores the invoice action',async()=>{
    const {controller,frappe}=setup(true);
    await controller.prepare_app_defaults({name:'opening'});
    frappe.ie_pos.apply_state(controller,'Cerrado');
    assert.equal(controller.primary.label,'Abrir nuevo turno');
    assert.equal(controller.inert,true);
    frappe.ie_pos.apply_state(controller,'Abierto');
    assert.equal(controller.primary.label,'New Invoice');
    assert.equal(controller.inert,false);
});

test('cashiers without closing permissions can still inspect the state',async()=>{
    const {controller,frappe,actions}=setup(true);
    frappe.ie_pos.call=async()=>({enabled:true,estado:'Error',puede_cerrar:false});
    await controller.prepare_app_defaults({name:'opening'});
    controller.prepare_btns();
    assert.equal(actions.at(-1).label,'Estado del turno');
    assert.equal(actions.at(-1).group,undefined);
});

test('a fresh POS discovers pending closings and still allows opening another profile',async()=>{
    const {controller,frappe,calls}=setup(true);
    const pending=[{name:'old-opening',estado:'Error'}];
    frappe.ie_pos.call=async()=>({enabled:true,pendientes:pending});
    frappe.ie_pos.recover_opening=(owner,turns,other)=>{
        assert.equal(owner,controller);assert.equal(turns,pending);other();
    };
    await controller.create_opening_voucher();
    assert.equal(calls.filter(call=>call==='native-opening').length,1);
});

test('ordinary openings keep the native workflow when there are no pending closings',async()=>{
    for (const enabled of [true,false]) {
        const {controller,calls}=setup(enabled);
        await controller.create_opening_voucher();
        assert.ok(calls.includes('native-opening'));
    }
});

test('a terminal opening returned by ERPNext does not load an unusable invoice screen',async()=>{
    for (const estado of ['Cerrado','Cancelado']) {
        const {controller,frappe,calls}=setup(true);
        frappe.ie_pos.call=async(_,args)=>args?.opening ? {enabled:true,estado} : {enabled:true,pendientes:[]};
        await controller.prepare_app_defaults({name:'old-opening'});
        assert.ok(calls.includes('native-opening'));
        assert.ok(!calls.includes('defaults'));
    }
});

test('queued native closing cannot announce completion or unlock another turn',async()=>{
    const {controller,events}=setup(true);
    await controller.prepare_app_defaults({name:'opening'});
    controller.setup_listener_for_pos_closing();
    assert.equal(events.native,undefined);
    events.ie_pos_turn({opening:'other',estado:'Cerrado'});
    assert.equal(controller.ie_state,undefined);
    events.ie_pos_turn({opening:'opening',estado:'Cerrando app'});
    assert.equal(controller.inert,true);
    events.ie_pos_turn({opening:'opening',estado:'Abierto'});
    assert.equal(controller.inert,false);
});

test('loading POS again installs only one set of actions',async()=>{
    const {frappe,controller,actions}=setup(true);
    await frappe.pages['point-of-sale'].on_page_load({});
    await controller.prepare_app_defaults({name:'opening'});controller.prepare_btns();
    assert.equal(actions.length,4);
});

test('integrated overnight turns skip the native obsolete-date warning',async()=>{
    const integrated=setup(true), native=setup(false);
    await integrated.controller.prepare_app_defaults({name:'opening'});
    await native.controller.prepare_app_defaults({name:'opening'});
    integrated.controller.check_outdated_pos_opening_entry();native.controller.check_outdated_pos_opening_entry();
    assert.ok(!integrated.calls.includes('outdated'));
    assert.ok(native.calls.includes('outdated'));
});
