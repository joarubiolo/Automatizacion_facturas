"use strict";
const $ = (id) => document.getElementById(id);
const labels = {OK:"Correcta", OK_INFERIDO:"Inferida", REVISAR:"Para revisar", ERROR:"Error", DUPLICADO:"Duplicada"};
const stages = ["Descargando", "Leyendo PDF / OCR", "Detectando campos", "Verificando duplicados", "Guardando en Sheets", "Organizando en Drive"];
const stageLabels = ["Descarga", "OCR", "Campos", "Control", "Sheets", "Drive"];
let page = 1, currentRows = [], state = null, invoiceRequest = 0, busy = false;
const currency = new Intl.NumberFormat("es-AR", {style:"currency", currency:"ARS", maximumFractionDigits:2});
const timeFormat = new Intl.DateTimeFormat("es-AR", {timeZone:"America/Argentina/Buenos_Aires", hour:"2-digit", minute:"2-digit", second:"2-digit"});
const dateFormat = new Intl.DateTimeFormat("es-AR", {timeZone:"America/Argentina/Buenos_Aires", dateStyle:"short", timeStyle:"short"});
function el(tag, className, text) { const node=document.createElement(tag); if(className) node.className=className; if(text!==undefined) node.textContent=text; return node; }
function text(id, value) { $(id).textContent=value; }
function badge(value) { return el("span", "badge " + (Object.hasOwn(labels,value) ? value : "neutral"), labels[value] || value || "Sin estado"); }
function bytes(value) { return Number.isFinite(value) ? (value / 1024 ** 3).toLocaleString("es-AR", {maximumFractionDigits:2}) + " GB" : "—"; }
function money(value) { if(value==="" || value===null || value===undefined) return "—"; let number=typeof value==="number"?value:Number(String(value).includes(",")?String(value).replace(/\./g,"").replace(",","."):value); return Number.isFinite(number)?currency.format(number):String(value); }
function timestamp(value, full=false) { const date=new Date(value); return value && !Number.isNaN(date.getTime()) ? (full?dateFormat:timeFormat).format(date):"—"; }
function duration(value) { if(!Number.isFinite(value)) return "—"; const seconds=Math.max(0,Math.floor(value)); return seconds<60?seconds+" s":Math.floor(seconds/60)+" min "+seconds%60+" s"; }
function alertMessage(message) { text("error-banner",message); $("error-banner").classList.toggle("hidden",!message); }
async function api(url) { const response=await fetch(url,{cache:"no-store",credentials:"same-origin"}); if(response.status===401) {location.replace("/login"); throw new Error("Sesión vencida");} if(!response.ok) throw new Error("No se pudo consultar el panel"); return response.json(); }
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
  renderCurrent(data); renderEvents(data.events || []);
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
function renderEvents(events) {
  const list=$("activity-list"); list.replaceChildren();
  if(!events.length) {list.append(el("p","muted empty-small","Todavía no hay eventos de procesamiento."));return;}
  events.forEach(event=>{
    const row=el("div","activity-item"), time=el("time","",timestamp(event.at)); time.dateTime=event.at || ""; time.title=timestamp(event.at,true);
    const content=el("div"); const titles={start:"Automatización iniciada",stop:"Worker detenido",file_start:"Comenzó el procesamiento",result:"Procesamiento finalizado",cycle_end:"Ciclo completado",cycle_error:"Error en el ciclo"};
    content.append(el("div","",titles[event.kind] || event.kind));
    let detail=event.archivo || (event.kind==="cycle_end"?event.detected+" detectadas · "+(event.counts?.OK || 0)+" correctas · "+(event.counts?.REVISAR || 0)+" para revisar":event.error || "");
    if(event.kind==="result" && event.observaciones) detail+=" · "+event.observaciones;
    if(detail) content.append(el("div","activity-detail",detail));
    row.append(time,content); if(event.estado) row.append(badge(event.estado)); list.append(row);
  });
}
async function loadInvoices() {
  const requestId=++invoiceRequest;
  const params=new URLSearchParams({page:String(page),size:"25",q:$("search").value,state:$("state-filter").value});
  const data=await api("/api/invoices?"+params); if(requestId!==invoiceRequest) return;
  if(page>1 && !data.records.length && data.total) {page=Math.max(1,Math.ceil(data.total/25));return loadInvoices();}
  currentRows=data.records;
  text("count-total",data.all_total);text("count-ok",data.counts.OK || 0);text("count-inferred",data.counts.OK_INFERIDO || 0);text("count-review",data.counts.REVISAR || 0);
  text("history-time",data.synced_at?"Sincronizado: "+timestamp(data.synced_at):"Esperando sincronización con Sheets");
  const rows=$("invoice-rows");rows.replaceChildren();
  if(!data.records.length) {const row=el("tr"), cell=el("td","empty-table",data.synced_at?"No hay facturas que coincidan con tu búsqueda.":"El historial se cargará cuando el worker complete su primer ciclo.");cell.colSpan=8;row.append(cell);rows.append(row);}
  data.records.forEach((invoice,index)=>{
    const row=el("tr"), name=el("td");name.append(el("div","file-name",invoice.archivo || "Sin nombre"),el("div","provider-name",invoice.proveedor || "Proveedor sin detectar"));name.title=invoice.archivo+" · "+invoice.proveedor;
    const result=el("td");result.append(badge(invoice.estado));row.append(name,el("td","",invoice.fecha_factura || "—"),result);
    ["neto","iva","importe_otros_tributos","total"].forEach(key=>row.append(el("td","numeric",money(invoice[key]))));
    const action=el("td"), button=el("button","row-button","Ver detalle");button.type="button";button.setAttribute("aria-label","Ver detalle de "+invoice.archivo);button.addEventListener("click",()=>showInvoice(currentRows[index]));action.append(button);row.append(action);rows.append(row);
  });
  const start=data.total?(page-1)*25+1:0,end=Math.min(page*25,data.total);
  text("page-info",start+"–"+end+" de "+data.total+" facturas");$("previous").disabled=page===1;$("next").disabled=page*25>=data.total;
}
function showInvoice(invoice) {
  text("dialog-title",invoice.archivo || "Factura");const content=$("dialog-content");content.replaceChildren();
  const grid=el("dl","detail-grid"); const fields={estado:"Resultado",fecha_factura:"Fecha de factura",fecha_carga:"Fecha de procesamiento",proveedor:"Proveedor",cuit_proveedor:"CUIT proveedor",cliente:"Cliente",cuit_cliente:"CUIT cliente",tipo:"Tipo",punto_venta:"Punto de venta",numero:"Número",neto:"Neto",iva:"IVA",importe_otros_tributos:"Otros tributos",total:"Total",detalle:"Concepto",observaciones:"Observaciones",cae:"CAE",vencimiento_cae:"Vencimiento CAE"};
  Object.entries(fields).forEach(([key,label])=>{const item=el("div","detail-item "+(["detalle","observaciones"].includes(key)?"wide":""));item.append(el("dt","",label));const value=el("dd"); if(key==="estado") value.append(badge(invoice[key]));else value.textContent=["neto","iva","importe_otros_tributos","total"].includes(key)?money(invoice[key]):String(invoice[key] || "—");item.append(value);grid.append(item);});
  if(/^[A-Za-z0-9_-]+$/.test(invoice.drive_id)) {const item=el("div","detail-item wide"), link=el("a","","Abrir documento en Google Drive ↗");link.href="https://drive.google.com/file/d/"+encodeURIComponent(invoice.drive_id)+"/view";link.target="_blank";link.rel="noopener noreferrer";item.append(link);grid.append(item);}
  content.append(grid);$("invoice-dialog").showModal();
}
async function refresh() { if(busy)return;busy=true;$("refresh").disabled=true;try {await Promise.all([api("/api/status").then(renderStatus),loadInvoices()]);}catch(error){alertMessage(error.message+". Se volverá a intentar automáticamente.");}finally{busy=false;$("refresh").disabled=false;} }
$("refresh").addEventListener("click",refresh);
let debounce;$("search").addEventListener("input",()=>{clearTimeout(debounce);debounce=setTimeout(()=>{page=1;loadInvoices().catch(error=>alertMessage(error.message));},250);});
$("state-filter").addEventListener("change",()=>{page=1;loadInvoices().catch(error=>alertMessage(error.message));});
$("previous").addEventListener("click",()=>{page--;loadInvoices().catch(error=>alertMessage(error.message));});$("next").addEventListener("click",()=>{page++;loadInvoices().catch(error=>alertMessage(error.message));});
$("close-dialog").addEventListener("click",()=>$("invoice-dialog").close());
document.addEventListener("visibilitychange",()=>{if(!document.hidden)refresh();});
refresh();setInterval(()=>{if(!document.hidden)refresh();},5000);setInterval(updateElapsed,1000);
