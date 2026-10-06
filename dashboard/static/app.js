"use strict";
const $ = (id) => document.getElementById(id);
const labels = {OK:"Correcta", OK_INFERIDO:"Inferida", REVISAR:"Para revisar", ERROR:"Error", DUPLICADO:"Duplicada"};
const stages = ["Descargando", "Leyendo PDF / OCR", "Detectando campos", "Verificando duplicados", "Guardando en Sheets", "Organizando en Drive"];
const stageLabels = ["Descarga", "OCR", "Campos", "Control", "Sheets", "Drive"];
let page = 1, currentRows = [], state = null, invoiceRequest = 0, busy = false;
let editingInvoice = null, detailInvoice = null, requestKey = crypto.randomUUID(), dirty = false, saving = false, loadingEditor = false;
const currency = new Intl.NumberFormat("es-AR", {style:"currency", currency:"ARS", maximumFractionDigits:2});
const timeFormat = new Intl.DateTimeFormat("es-AR", {timeZone:"America/Argentina/Buenos_Aires", hour:"2-digit", minute:"2-digit", second:"2-digit"});
const dateFormat = new Intl.DateTimeFormat("es-AR", {timeZone:"America/Argentina/Buenos_Aires", dateStyle:"short", timeStyle:"short"});
function el(tag, className, text) { const node=document.createElement(tag); if(className) node.className=className; if(text!==undefined) node.textContent=text; return node; }
function text(id, value) { $(id).textContent=value; }
function badge(value) { return el("span", "badge " + (Object.hasOwn(labels,value) ? value : "neutral"), labels[value] || value || "Sin estado"); }
function bytes(value) { return Number.isFinite(value) ? (value / 1024 ** 3).toLocaleString("es-AR", {maximumFractionDigits:2}) + " GB" : "—"; }
function numericAmount(value) { if(value==="" || value===null || value===undefined) return null; if(typeof value==="number") return Number.isFinite(value)?value:null; let raw=String(value).trim().replace(/[$\s]/g,""); if(!/^-?\d+(?:[.,]\d+)*$/.test(raw)) return null; if(raw.includes(",")) raw=raw.replace(/\./g,"").replace(",","."); else if((raw.match(/\./g)||[]).length>1 || /\.\d{3}$/.test(raw)) raw=raw.replace(/\./g,""); const result=Number(raw);return Number.isFinite(result)?result:null; }
function money(value) { const number=numericAmount(value);return number===null?(value==="" || value===null || value===undefined?"—":String(value)):currency.format(number); }
function timestamp(value, full=false) { const date=new Date(value); return value && !Number.isNaN(date.getTime()) ? (full?dateFormat:timeFormat).format(date):"—"; }
function duration(value) { if(!Number.isFinite(value)) return "—"; const seconds=Math.max(0,Math.floor(value)); return seconds<60?seconds+" s":Math.floor(seconds/60)+" min "+seconds%60+" s"; }
function alertMessage(message) { text("error-banner",message); $("error-banner").classList.toggle("hidden",!message); }
async function api(url, options={}) { const response=await fetch(url,{cache:"no-store",credentials:"same-origin",...options}); if(response.status===401) {location.replace("/login"); throw new Error("Sesión vencida");} const data=await response.json().catch(()=>({})); if(!response.ok) {const error=new Error(data.error || "No se pudo completar la solicitud");error.fields=data.fields || {};throw error;} return data; }
function setMetric(id, value, percent, detail) { text(id+"-value",value); $(id+"-bar").value=Math.max(0,Math.min(100,percent || 0)); text(id+"-detail",detail); }
function renderStatus(data) {
  state=data;
  const health={healthy:["Sistema operativo","green"],warning:["El sistema necesita atención","amber"],offline:["Worker sin conexión","red"]}[data.health] || ["Estado desconocido","amber"];
  text("health-text",health[0]); $("health-dot").className="dot "+health[1];
  const statusLabels={idle:"Esperando nuevas facturas",processing:"Procesando facturas",checking:"Consultando Google Drive",starting:"Iniciando worker",error:"Error en el último ciclo",stopped:"Worker detenido"};
  text("worker-status",data.stale?"Los datos pueden estar desactualizados":statusLabels[data.status] || "Esperando el primer ciclo");
  text("last-update","Señal del worker: "+timestamp(data.heartbeat_at));
  const m=data.metrics || {};
  setMetric("cpu",Number.isFinite(m.cpu_percent)?m.cpu_percent.toLocaleString("es-AR")+" %":"—",m.cpu_percent,(m.cpu_count || "—")+" CPU · OCR "+(Number.isFinite(m.worker_cpu_percent)?m.worker_cpu_percent.toLocaleString("es-AR")+" %":"—"));
  setMetric("memory",bytes(m.memory_used),100*m.memory_used/m.memory_total,bytes(m.memory_available)+" disponibles de "+bytes(m.memory_total));
  setMetric("worker-memory",bytes(m.worker_memory),100*m.worker_memory/m.worker_memory_limit,"Límite del OCR: "+bytes(m.worker_memory_limit));
  setMetric("disk",bytes(m.disk_total-m.disk_available),100*(1-m.disk_available/m.disk_total),bytes(m.disk_available)+" libres de "+bytes(m.disk_total));
  text("uptime","Instancia encendida: "+(Number.isFinite(m.uptime_seconds)?Math.floor(m.uptime_seconds/3600)+" h":"—"));
  renderCurrent(data);
  alertMessage(data.stale?"No llega la señal del worker. El historial sigue disponible, pero las métricas y el procesamiento pueden estar desactualizados.":data.history_error?"No se pudo actualizar Google Sheets. Mostramos la última copia disponible.":data.last_cycle_error?"El último ciclo falló ("+data.last_cycle_error+"). El worker volverá a intentarlo.":data.metrics_error?"No se pudieron obtener las métricas de la instancia.":"");
}
function renderCurrent(data) {
  const container=$("current-content"); container.replaceChildren();
  const current=data.current;
  const processing=!!current && !data.stale && data.status!=="stopped";
  $("stage-track").classList.toggle("hidden",!processing);
  const b=$("processing-badge"); b.className="badge "+(data.stale?"offline":processing?"processing":"neutral"); b.textContent=data.stale?"Sin señal":processing?"En curso":data.status==="error"?"Error":"En espera";
  if(current) {
    container.append(el("h3","",current.archivo),el("div","stage-name",current.stage || "Iniciando"),el("p","muted",data.stale?"Último estado conocido; el worker no envía señal.":"El archivo avanza automáticamente por las etapas de procesamiento."));
    const stage=stages.indexOf(current.stage), track=$("stage-track"); track.replaceChildren();
    stageLabels.forEach((label,i)=>track.append(el("span","stage-item "+(i<stage?"done":i===stage?"current":""),label)));
  } else {
    container.append(el("div","idle-symbol",data.stale?"!":"✓"),el("h3","",data.stale?"Sin señal del procesador":data.status==="error"?"El worker volverá a intentar":data.status==="starting"?"Iniciando automatización":"Listo para la próxima factura"),el("p","muted",data.stale?"Revisá el servicio en la instancia Oracle.":"Subí archivos a la carpeta Entrada de Google Drive."));
  }
  const queue=(data.queue || []).filter(item=>item.id!==current?.drive_id);
  text("queue-count",queue.length); const list=$("queue-list"); list.replaceChildren();
  if(!queue.length) list.append(el("p","muted empty-small",data.stale?"Última cola conocida vacía.":"No hay facturas esperando."));
  queue.forEach((item,i)=>{const row=el("div","queue-item"); row.append(el("span","queue-number",String(i+1).padStart(2,"0")),el("span","",item.archivo)); list.append(row);});
  text("cycle-time","Último ciclo: "+timestamp(data.last_cycle_at)); updateElapsed();
}
function updateElapsed() { text("elapsed",state?.current?"Tiempo en curso: "+duration((Date.now()-new Date(state.current.started_at))/1000):"Consulta cada "+(state?.interval || 60)+" s"); }
async function loadInvoices() {
  const requestId=++invoiceRequest;
  const params=new URLSearchParams({page:String(page),size:"25",q:$("search").value,state:$("state-filter").value,month:$("month-filter").value,year:$("year-filter").value});
  const data=await api("/api/invoices?"+params); if(requestId!==invoiceRequest) return;
  if(page>1 && !data.records.length && data.total) {page=Math.max(1,Math.ceil(data.total/25));return loadInvoices();}
  currentRows=data.records;
  text("count-total",data.summary.count);text("count-ok",data.counts.OK || 0);text("count-inferred",data.counts.OK_INFERIDO || 0);text("count-review",data.counts.REVISAR || 0);
  renderSummary(data);
  text("history-time",data.synced_at?"Sincronizado: "+timestamp(data.synced_at):"Esperando sincronización con Sheets");
  const rows=$("invoice-rows");rows.replaceChildren();
  if(!data.records.length) {const row=el("tr"), cell=el("td","empty-table",data.synced_at?"No hay facturas que coincidan con tu búsqueda.":"El historial se cargará cuando el worker complete su primer ciclo.");cell.colSpan=8;row.append(cell);rows.append(row);}
  data.records.forEach((invoice,index)=>{
    const row=el("tr"), name=el("td");name.append(el("div","file-name",invoice.archivo || "Sin nombre"),el("div","provider-name",invoice.proveedor || "Proveedor sin detectar"));name.title=invoice.archivo+" · "+invoice.proveedor;
    const result=el("td");result.append(badge(invoice.estado));row.append(name,el("td","",invoice.fecha_factura || "—"),result);
    ["neto","iva","importe_otros_tributos","total"].forEach(key=>row.append(el("td","numeric",money(invoice[key]))));
    const action=el("td","row-actions"), button=el("button","row-button","Ver detalle");button.type="button";button.setAttribute("aria-label","Ver detalle de "+invoice.archivo);button.addEventListener("click",()=>showInvoice(currentRows[index]));action.append(button);
    const edit=el("button","edit-button","Corregir");edit.type="button";edit.disabled=!data.editing_enabled;edit.setAttribute("aria-label","Corregir "+invoice.archivo);edit.addEventListener("click",()=>openEditor(currentRows[index]));action.append(edit);row.append(action);rows.append(row);
  });
  const start=data.total?(page-1)*25+1:0,end=Math.min(page*25,data.total);
  text("page-info",start+"–"+end+" de "+data.total+" facturas");$("previous").disabled=page===1;$("next").disabled=page*25>=data.total;
}
function showInvoice(invoice) {
  detailInvoice=invoice;
  text("dialog-title",invoice.archivo || "Factura");const content=$("dialog-content");content.replaceChildren();
  const grid=el("dl","detail-grid"); const fields={estado:"Resultado",fecha_factura:"Fecha de factura",fecha_carga:"Fecha de procesamiento",proveedor:"Proveedor",cuit_proveedor:"CUIT proveedor",cliente:"Cliente",cuit_cliente:"CUIT cliente",tipo:"Tipo",punto_venta:"Punto de venta",numero:"Número",neto:"Neto",iva:"IVA",importe_otros_tributos:"Otros tributos",total:"Total",detalle:"Concepto",observaciones:"Observaciones",cae:"CAE",vencimiento_cae:"Vencimiento CAE"};
  Object.entries(fields).forEach(([key,label])=>{const item=el("div","detail-item "+(["detalle","observaciones"].includes(key)?"wide":""));item.append(el("dt","",label));const value=el("dd"); if(key==="estado") value.append(badge(invoice[key]));else value.textContent=["neto","iva","importe_otros_tributos","total"].includes(key)?money(invoice[key]):String(invoice[key] || "—");item.append(value);grid.append(item);});
  if(/^[A-Za-z0-9_-]+$/.test(invoice.drive_id)) {const item=el("div","detail-item wide"), link=el("a","","Abrir documento en Google Drive ↗");link.href="https://drive.google.com/file/d/"+encodeURIComponent(invoice.drive_id)+"/view";link.target="_blank";link.rel="noopener noreferrer";item.append(link);grid.append(item);}
  content.append(grid);$("invoice-dialog").showModal();
}
function renderSummary(data) {
  const year=$("year-filter"), selected=year.value;
  const years=[...new Set([...data.years,...(selected?[Number(selected)]:[])])].sort((a,b)=>b-a);
  if(JSON.stringify(years)!==year.dataset.years) {year.replaceChildren(new Option("Todos los años",""),...years.map(value=>new Option(String(value),String(value))));year.value=selected;year.dataset.years=JSON.stringify(years);}
  const summary=data.summary;
  text("period-total",money(summary.amounts.total));text("period-net",money(summary.amounts.neto));text("period-vat",money(summary.amounts.iva));text("period-other",money(summary.amounts.importe_otros_tributos));
  text("period-count",summary.count+" "+(summary.count===1?"factura":"facturas")+" en este periodo");
  const notes=[];if(summary.missing_total)notes.push(summary.missing_total+" sin un total válido, fuera de la suma");if(summary.missing_date)notes.push(summary.missing_date+" sin fecha de emisión");
  text("period-note",notes.length?notes.join(" · "):summary.count?"El periodo también filtra el historial. La suma incluye facturas correctas y para revisar.":"No hay facturas en el periodo seleccionado.");
  $("new-invoice").disabled=!data.editing_enabled;$("edit-detail").disabled=!data.editing_enabled;
}
function formMessage(message, kind="error") { const node=$("form-message");node.textContent=message;node.className="form-message "+kind+(message?"":" hidden"); }
function clearFieldErrors() {document.querySelectorAll(".field-error").forEach(node=>node.textContent="");$("invoice-form").querySelectorAll("[aria-invalid]").forEach(node=>node.removeAttribute("aria-invalid"));}
function dateInput(value) { if(!value)return "";if(/^\d{4}-\d{2}-\d{2}$/.test(value))return value;const match=String(value).match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);return match?match[3]+"-"+match[2].padStart(2,"0")+"-"+match[1].padStart(2,"0"):""; }
function populateForm(invoice=null) {
  $("invoice-form").reset();clearFieldErrors();editingInvoice=invoice;dirty=false;requestKey=crypto.randomUUID();
  $("invoice-form").querySelectorAll("[name]").forEach(input=>{const value=invoice?.[input.name] ?? "";if(input.name==="estado")input.value="";else if(input.type==="date")input.value=dateInput(value);else input.value=String(value);});
  if(!invoice){$("field-iva").value="0,00";$("field-importe_otros_tributos").value="0,00";}
  text("editor-heading",invoice?"Corregir factura":"Carga manual");text("editor-mode",invoice?"Edición":"Nueva factura");text("editor-caption",invoice?"Los cambios se guardan sobre la factura seleccionada en el historial.":"Ingresá los datos del comprobante para incorporarlo al historial.");text("save-invoice",invoice?"Guardar cambios":"Guardar factura");updateAmountCheck();
}
function revealEditor() {$("manual-details").open=true;$("manual").scrollIntoView({behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"start"});}
function canSwitchEditor() {if(saving || loadingEditor)return false;if(dirty){revealEditor();formMessage("Tenés cambios sin guardar. Guardalos o usá Cancelar antes de abrir otra factura.","warning");return false;}return true;}
function newInvoice() {if(!canSwitchEditor())return;populateForm();formMessage("");revealEditor();$("field-fecha_factura").focus({preventScroll:true});}
async function openEditor(invoice) {
  if(!canSwitchEditor())return;revealEditor();formMessage("Consultando los datos actuales de la factura…","neutral");
  loadingEditor=true;$("invoice-form").querySelectorAll("fieldset").forEach(node=>node.disabled=true);$("save-invoice").disabled=true;$("cancel-edit").disabled=true;
  try {const data=await api("/api/invoices/"+invoice._ref);populateForm(data.invoice);formMessage("");$("field-fecha_factura").focus({preventScroll:true});}catch(error){formMessage(error.message);}
  finally {loadingEditor=false;$("invoice-form").querySelectorAll("fieldset").forEach(node=>node.disabled=false);$("save-invoice").disabled=false;$("cancel-edit").disabled=false;}
}
function updateAmountCheck() {
  const amounts=["neto","iva","importe_otros_tributos"].map(key=>numericAmount($("field-"+key).value)), total=numericAmount($("field-total").value);
  const complete=amounts.every(value=>value!==null), expected=complete?amounts.reduce((sum,value)=>sum+Math.round(value*100),0)/100:null;
  $("calculate-total").disabled=!complete || saving;
  const equal=complete && total!==null && Math.abs(Math.round(expected*100)-Math.round(total*100))<=2;
  const node=$("amount-check-text");node.classList.toggle("amount-mismatch",complete && total!==null && !equal);
  node.textContent=!complete?"Completá Neto, IVA y Otros para verificar la suma.":equal?"Los importes coinciden con el total.":"Neto + IVA + Otros = "+money(expected)+(total===null?". Podés usar Calcular total.":". Revisá la diferencia con el total ingresado.");
}
async function saveInvoice(event) {
  event.preventDefault();if(saving || loadingEditor)return;clearFieldErrors();
  const form=$("invoice-form"), invoice=Object.fromEntries(new FormData(form));
  if(form.dataset.enabled!=="true"){formMessage("La carga manual todavía no está disponible.");return;}
  saving=true;$("save-invoice").disabled=true;text("save-invoice","Guardando…");formMessage("Guardando los datos de la factura…","neutral");
  form.querySelectorAll("fieldset").forEach(node=>node.disabled=true);$("cancel-edit").disabled=true;
  try {
    const result=await api(editingInvoice?"/api/invoices/"+editingInvoice._ref:"/api/invoices",{method:editingInvoice?"PUT":"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify({invoice,revision:editingInvoice?._revision,request_key:requestKey})});
    populateForm(result.invoice);formMessage(result.warnings.length?"Guardada para revisar: "+result.warnings.join(". "):"Factura guardada. El historial y los totales ya están actualizados.",result.warnings.length?"warning":"success");await loadInvoices().catch(error=>alertMessage("La factura se guardó, pero falta actualizar el historial. "+error.message));
  } catch(error) {
    formMessage(error.message);let first=null;Object.entries(error.fields || {}).forEach(([key,message])=>{const input=$("field-"+key), output=$("error-"+key);if(input && output){output.textContent=message;input.setAttribute("aria-invalid","true");first ||= input;}});if(first)first.focus();
  } finally {saving=false;form.querySelectorAll("fieldset").forEach(node=>node.disabled=false);$("cancel-edit").disabled=false;$("save-invoice").disabled=false;text("save-invoice",editingInvoice?"Guardar cambios":"Guardar factura");updateAmountCheck();}
}
async function refresh() { if(busy)return;busy=true;$("refresh").disabled=true;try {await Promise.all([api("/api/status").then(renderStatus),loadInvoices()]);}catch(error){alertMessage(error.message+". Se volverá a intentar automáticamente.");}finally{busy=false;$("refresh").disabled=false;} }
$("refresh").addEventListener("click",refresh);
let debounce;$("search").addEventListener("input",()=>{clearTimeout(debounce);debounce=setTimeout(()=>{page=1;loadInvoices().catch(error=>alertMessage(error.message));},250);});
$("state-filter").addEventListener("change",()=>{page=1;loadInvoices().catch(error=>alertMessage(error.message));});
["month-filter","year-filter"].forEach(id=>$(id).addEventListener("change",()=>{page=1;loadInvoices().catch(error=>alertMessage(error.message));}));
$("previous").addEventListener("click",()=>{page--;loadInvoices().catch(error=>alertMessage(error.message));});$("next").addEventListener("click",()=>{page++;loadInvoices().catch(error=>alertMessage(error.message));});
$("close-dialog").addEventListener("click",()=>$("invoice-dialog").close());
$("new-invoice").addEventListener("click",newInvoice);$("manual-nav").addEventListener("click",()=>{$("manual-details").open=true;});
$("edit-detail").addEventListener("click",()=>{$("invoice-dialog").close();openEditor(detailInvoice);});
$("invoice-form").addEventListener("submit",saveInvoice);$("invoice-form").addEventListener("input",()=>{dirty=true;updateAmountCheck();});$("invoice-form").addEventListener("change",()=>{dirty=true;});
$("cancel-edit").addEventListener("click",()=>{if(saving)return;populateForm();formMessage("");$("manual-details").open=false;});
$("calculate-total").addEventListener("click",()=>{const values=["neto","iva","importe_otros_tributos"].map(key=>numericAmount($("field-"+key).value));if(values.some(value=>value===null))return;const total=values.reduce((sum,value)=>sum+Math.round(value*100),0)/100;$("field-total").value=total.toLocaleString("es-AR",{minimumFractionDigits:2,maximumFractionDigits:2,useGrouping:false});dirty=true;updateAmountCheck();});
populateForm();
document.addEventListener("visibilitychange",()=>{if(!document.hidden)refresh();});
refresh();setInterval(()=>{if(!document.hidden)refresh();},5000);setInterval(updateElapsed,1000);
