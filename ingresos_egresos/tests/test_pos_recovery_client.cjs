const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(estado, {canClose = true, canCancel = false, erp = null, operation = ''} = {}) {
    const state = {estado, erp_estado: erp, operacion: operation};
    const calls = [], dialogs = [], messages = [], timers = new Set();
    let reloads = 0;
    const wrapper = () => ({html(value) {this.content=value;return this;}});
    const frappe = {ie_pos: {}, provide() {}, utils: {escape_html: text=>String(text).replaceAll('<','&lt;').replaceAll('>','&gt;')},
        msgprint: message=>messages.push(message), set_route: route=>calls.push({method:'route',route}),
        ui: {Dialog: class {
            constructor(options) {
                this.options=options;this.fields_dict={};this.values={};
                this.button={label:options.primary_action_label,text(value) {this.label=value;return this;},prop() {return this;}};
                for (const field of options.fields) {
                    if (!field.fieldname) continue;
                    this.fields_dict[field.fieldname]={df:{...field},$wrapper:wrapper()};
                    this.values[field.fieldname]=field.data || field.default;
                }
                dialogs.push(this);
            }
            get_value(name) {return this.values[name];}
            get_primary_btn() {return this.button;}
            set_df_property(name,property,value) {this.fields_dict[name].df[property]=value;}
            show() {this.visible=true;}
            hide() {this.visible=false;this.options.onhide?.();}
        }}
    };
    const sandbox={frappe,__:value=>value,window:{location:{reload:()=>reloads++}},
        setInterval: callback=>{timers.add(callback);return callback;},clearInterval: callback=>timers.delete(callback)};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/js/ie_pos_modals.js'),'utf8'),sandbox);
    frappe.ie_pos.call=async(method,args)=>{
        calls.push({method,args});
        if (method==='context') return {estado:state.estado,perfil:'Caja QA',moneda_empresa:'NIO',puede_cerrar:canClose,puede_anular:canCancel};
        if (method==='report') return {esperado_empresa:{Cash:100}};
        return {...state};
    };
    return {api:frappe.ie_pos,state,calls,dialogs,messages,timers,reloads:()=>reloads};
}

test('an expense attempted on a closed turn opens its actual closing status and the new-turn action',async()=>{
    const app=setup('Cerrado',{erp:'Submitted'});
    const controller={page:{},$components_wrapper:{prop(){}}};
    await app.api.movement('opening','Egreso',controller);
    const dialog=app.dialogs[0];
    assert.match(dialog.options.title,/Cierre conjunto/);
    assert.equal(dialog.button.label,'Abrir nuevo turno');
    assert.match(dialog.fields_dict.estado.$wrapper.content,/finalizaron/);
    await dialog.options.primary_action();
    assert.equal(app.reloads(),1);
    assert.equal(app.calls.some(call=>['register_movement','start_closing','retry'].includes(call.method)),false);
});

test('ERP queued state offers refresh without submitting another closing',async()=>{
    const app=setup('Cerrando POS',{erp:'Queued'});
    await app.api.closing('opening');
    const dialog=app.dialogs[0];
    assert.equal(dialog.button.label,'Actualizar estado');
    assert.match(dialog.fields_dict.estado.$wrapper.content,/en cola/);
    await dialog.options.primary_action();
    assert.equal(app.calls.some(call=>['start_closing','retry'].includes(call.method)),false);
    assert.equal(app.timers.size,1);
    dialog.hide();
    assert.equal(app.timers.size,0);
});

test('an app-stage failure offers continuation and keeps the existing ERP closing',async()=>{
    const app=setup('Error',{erp:'Submitted'});
    app.state.error='<Error de prueba>';
    await app.api.closing('opening');
    const dialog=app.dialogs[0];
    assert.equal(dialog.button.label,'Continuar cierre');
    assert.match(dialog.fields_dict.estado.$wrapper.content,/Se conservará el cierre existente/);
    assert.match(dialog.fields_dict.estado.$wrapper.content,/&lt;Error de prueba&gt;/);
    await dialog.options.primary_action();
    assert.equal(app.calls.filter(call=>call.method==='retry').length,1);
    assert.equal(app.calls.some(call=>call.method==='start_closing'),false);
    dialog.hide();
});

test('read-only operators receive instructions and cannot retry or submit a closing',async()=>{
    for (const estado of ['Abierto','Error']) {
        const app=setup(estado,{canClose:false});
        await app.api.closing('opening');
        const dialog=app.dialogs[0];
        assert.equal(dialog.button.label,'Actualizar estado');
        assert.equal(dialog.fields_dict.arqueo.df.hidden,1);
        assert.match(dialog.fields_dict.estado.$wrapper.content,/usuario autorizado/);
        await dialog.options.primary_action();
        assert.equal(app.calls.some(call=>['start_closing','retry'].includes(call.method)),false);
        dialog.hide();
    }
});

test('cancellation recovery requires cancellation permissions and can return to the POS when completed',async()=>{
    const app=setup('Anulando',{operation:'Anulacion',canClose:true});
    await app.api.closing('opening');
    assert.equal(app.dialogs[0].button.label,'Actualizar estado');
    app.dialogs[0].hide();
    const supervisor=setup('Error',{operation:'Anulacion',canClose:false,canCancel:true});
    await supervisor.api.closing('opening');
    assert.equal(supervisor.dialogs[0].button.label,'Reintentar anulación');
    supervisor.dialogs[0].hide();
    const cancelled=setup('Cancelado');
    await cancelled.api.closing('opening');
    await cancelled.dialogs[0].options.primary_action();
    assert.ok(cancelled.calls.some(call=>call.method==='route'&&call.route==='point-of-sale'));
});

test('pending-turn selection provides recovery and leaves another profile opening available',async()=>{
    const app=setup('Error');
    let other=0, selected;
    app.api.closing=async opening=>{selected=opening;};
    const turns=[{name:'first',pos_profile:'Caja A',sucursal:'QA',estado:'Error'},
        {name:'second',pos_profile:'Caja B',sucursal:'QA',estado:'Cerrando app'}];
    const dialog=app.api.recover_opening({},turns,()=>other++);
    assert.equal(dialog.values.turno,'first');
    dialog.values.turno='second';
    await dialog.options.primary_action();
    assert.equal(selected,'second');
    dialog.options.secondary_action();
    assert.equal(other,1);
});

test('a delayed status poll cannot replace a completed recovery with an old error',async()=>{
    const app=setup('Error',{erp:'Submitted'});
    await app.api.closing('opening');
    const dialog=app.dialogs[0], call=app.api.call;
    let delayed, statusCalls=0;
    app.api.call=async(method,args)=>{
        if (method==='status' && ++statusCalls===1) {
            const old={...app.state};
            return new Promise(resolve=>{delayed=()=>resolve(old);});
        }
        if (method==='retry') app.state.estado='Cerrado';
        return call(method,args);
    };
    [...app.timers][0]();
    await dialog.options.primary_action();
    assert.equal(dialog.button.label,'Abrir nuevo turno');
    delayed();
    await new Promise(setImmediate);
    assert.equal(dialog.button.label,'Abrir nuevo turno');
    assert.equal(app.timers.size,0);
});
