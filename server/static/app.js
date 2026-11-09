const state = { user: null, csrf: "", setup: false, version: "", page: 1, pageSize: 50, total: 0, policies: [], departments: [], release: null, assetRequestSerial: 0, wallpaperExclusionRequestSerial: 0 };
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[ch]));
const fmtDate = (value) => value ? new Intl.DateTimeFormat("th-TH", {dateStyle:"short", timeStyle:"medium"}).format(new Date(value)) : "-";
const fmtBytes = (value) => { const n=Number(value||0); if(!n)return "0 B"; const u=["B","GB","TB"]; let v=n,i=0; if(v>=1073741824){v/=1073741824;i=1} if(v>=1024&&i===1){v/=1024;i=2} return `${v.toFixed(1)} ${u[i]}`; };
const departmentOptions = (selected="") => '<option value="">ยังไม่ระบุหน่วยงาน</option>'+state.departments.map(d=>`<option value="${esc(d)}" ${d===selected?"selected":""}>${esc(d)}</option>`).join("");

function toast(message, error=false) {
  const el=$("toast"); el.textContent=message; el.className=`toast show${error?" error":""}`;
  clearTimeout(toast.timer); toast.timer=setTimeout(()=>el.className="toast",3500);
}

async function api(path, options={}) {
  const opts={credentials:"same-origin",...options};
  opts.headers={"Content-Type":"application/json",...(options.headers||{})};
  if (opts.method && opts.method !== "GET" && state.csrf) opts.headers["X-CSRF-Token"]=state.csrf;
  const response=await fetch(path,opts);
  const type=response.headers.get("content-type")||"";
  const body=type.includes("json")?await response.json():await response.text();
  if(!response.ok) throw new Error(body.detail||body||`HTTP ${response.status}`);
  return body;
}

async function bootstrap() {
  try {
    const data=await api("/api/ui/bootstrap");
    state.setup=data.setup_required; state.user=data.user||null; state.csrf=data.user?.csrf_token||""; state.version=data.version||"";
    if(state.user) showApp(); else showAuth();
  } catch(error) { showAuth(); toast(error.message,true); }
}

function showAuth() {
  $("appView").classList.add("hidden"); $("authView").classList.remove("hidden");
  $("authTitle").textContent=state.setup?"ตั้งค่าผู้ดูแลระบบ":"เข้าสู่ระบบ HosMonitor";
  $("authHint").textContent=state.setup?"สร้างบัญชี Admin คนแรกสำหรับระบบนี้":"ระบบทะเบียนทรัพย์สินและติดตามสถานะเครื่องภายในโรงพยาบาล";
  $("authSubmit").textContent=state.setup?"สร้างบัญชี Admin":"เข้าสู่ระบบ";
  $("setupNotice").classList.toggle("hidden",!state.setup);
}

async function showApp() {
  $("authView").classList.add("hidden"); $("appView").classList.remove("hidden");
  $("currentUser").textContent=`${state.user.username} · ${state.user.role}`;
  $("currentVersion").textContent=`Server v${state.version||"-"}`;
  document.querySelectorAll(".admin-only").forEach(el=>el.classList.toggle("hidden",state.user.role!=="admin"));
  await refreshAssets();
}

$("authForm").addEventListener("submit", async event => {
  event.preventDefault();
  const payload={username:$("username").value.trim(),password:$("password").value};
  try {
    const data=await api(state.setup?"/api/ui/setup":"/api/ui/login",{method:"POST",body:JSON.stringify(payload)});
    state.user=data; state.csrf=data.csrf_token; state.setup=false; $("password").value=""; await showApp();
  } catch(error) { toast(error.message,true); }
});

$("logoutBtn").addEventListener("click",async()=>{try{await api("/api/ui/logout",{method:"POST"});}catch(_){} state.user=null;state.csrf="";showAuth();});
$("refreshBtn").addEventListener("click",()=>refreshCurrent());
document.querySelectorAll(".nav-item").forEach(button=>button.addEventListener("click",async()=>{
  document.querySelectorAll(".nav-item").forEach(item=>item.classList.remove("active")); button.classList.add("active");
  document.querySelectorAll(".view").forEach(view=>view.classList.add("hidden"));
  $(`${button.dataset.view}View`).classList.remove("hidden");
  const titles={assets:"ภาพรวมระบบ",control:"นโยบายและการเก็บข้อมูล",settings:"ตั้งค่า Agent",access:"ผู้ใช้และ Integration API",agentUpdates:"อัปเดต Agent",updates:"อัปเดตระบบ"}; $("pageTitle").textContent=titles[button.dataset.view];
  if(button.dataset.view==="control") await loadControl(); if(button.dataset.view==="settings") await loadSettings(); if(button.dataset.view==="access") await loadAccess(); if(button.dataset.view==="agentUpdates") await loadAgentUpdates(); if(button.dataset.view==="updates") await loadUpdates();
}));

async function refreshCurrent(){const active=document.querySelector(".nav-item.active")?.dataset.view||"assets";if(active==="assets")await refreshAssets();if(active==="control")await loadControl();if(active==="settings")await loadSettings();if(active==="access")await loadAccess();if(active==="agentUpdates")await loadAgentUpdates();if(active==="updates")await loadUpdates();}

$("filterForm").addEventListener("submit",event=>{event.preventDefault();state.page=1;loadAssets();});
let assetSearchTimer;
$("filterSearch").addEventListener("input",()=>{clearTimeout(assetSearchTimer);assetSearchTimer=setTimeout(()=>{state.page=1;loadAssets();},300);});
["filterDepartment","filterOnline","filterLifecycle"].forEach(id=>$(id).addEventListener("change",()=>{state.page=1;loadAssets();}));
$("prevPage").addEventListener("click",()=>{if(state.page>1){state.page--;loadAssets();}});
$("nextPage").addEventListener("click",()=>{if(state.page*state.pageSize<state.total){state.page++;loadAssets();}});

async function refreshAssets(){
  try {
    const dash=await api("/api/ui/dashboard");
    $("statTotal").textContent=dash.total;$("statOnline").textContent=dash.online;$("statOffline").textContent=dash.offline;$("statWarning").textContent=dash.disk_warning+dash.ram_warning;$("statRetired").textContent=dash.retired;
    state.departments=dash.departments; const select=$("filterDepartment"),current=select.value; select.innerHTML='<option value="">ทุกหน่วยงาน</option>'+dash.departments.map(d=>`<option value="${esc(d)}">${esc(d)}</option>`).join(""); select.value=current;
    const departmentHtml='<option value="">เลือกหน่วยงาน</option>'+dash.departments.map(d=>`<option value="${esc(d)}">${esc(d)}</option>`).join("");
    $("policyValue").innerHTML=departmentHtml;$("campaignDepartment").innerHTML=departmentHtml;
    await loadAssets(); $("updatedAt").textContent=`อัปเดต ${fmtDate(new Date().toISOString())}`;
  } catch(error){if(error.message.includes("login")){state.user=null;showAuth()}else toast(error.message,true);}
}

async function loadAssets(){
  const requestSerial=++state.assetRequestSerial;
  const params=new URLSearchParams({page:state.page,page_size:state.pageSize});
  const search=$("filterSearch").value.trim(),department=$("filterDepartment").value,online=$("filterOnline").value,retired=$("filterLifecycle").value==="retired";
  if(search)params.set("search",search);if(department)params.set("department",department);if(online)params.set("online",online);if(retired)params.set("retired","true");
  try {
    const data=await api(`/api/v1/assets?${params}`);if(requestSerial!==state.assetRequestSerial)return;state.total=data.total;
    $("assetRows").innerHTML=data.items.map(item=>{
      const disk=item.min_disk_free_percent==null?"-":`${Number(item.min_disk_free_percent).toFixed(0)}% free`;
      const warn=Number(item.min_disk_free_percent)<15||Number(item.ram_used_percent)>=85;
      const status=item.retired?`<span class="status-dot retired">เลิกใช้งาน${item.online?" · ยังออนไลน์":""}</span>`:`<span class="status-dot ${item.online?"online":""}">${item.online?"ออนไลน์":"ออฟไลน์"}</span>`;
      return `<tr data-id="${item.id}"><td>${status}</td><td><span class="asset-main">${esc(item.display_name||item.asset_tag||item.hostname)}</span><span class="asset-sub">${esc(item.hostname)}${item.asset_tag?` · ${esc(item.asset_tag)}`:""}</span></td><td>${esc(item.department||"-")}</td><td>${esc(item.os_name||"-")}<span class="asset-sub">${esc(item.os_version)}</span></td><td>${item.agent_version?`v${esc(item.agent_version)}`:"-"}</td><td>${esc(item.primary_ipv4||"-")}</td><td><span class="meter ${warn?"warn":""}">RAM ${Number(item.ram_used_percent).toFixed(0)}% · Disk ${esc(disk)}</span></td><td>${fmtDate(item.last_seen)}</td></tr>`;
    }).join("");
    $("emptyAssets").classList.toggle("hidden",data.items.length>0);$("pageInfo").textContent=`หน้า ${data.page} · ${data.total} รายการ`;
    document.querySelectorAll("#assetRows tr").forEach(row=>row.addEventListener("click",()=>openAsset(Number(row.dataset.id))));
  } catch(error){toast(error.message,true);}
}

async function openAsset(id){
  try {
    const item=await api(`/api/v1/assets/${id}`); $("detailTitle").textContent=item.display_name||item.asset_tag||item.hostname;
    const disks=item.disks.map(d=>`<div class="list-item"><span><b>${esc(d.device_id)} ${esc(d.label)}</b><small>${fmtBytes(d.free_bytes)} ว่าง จาก ${fmtBytes(d.total_bytes)}</small></span></div>`).join("")||'<p class="muted">ไม่มีข้อมูล</p>';
    const network=item.network.map(n=>`<div class="list-item"><span><b>${esc(n.ipv4)}${n.is_primary?" · Primary":""}</b><small>${esc(n.adapter_name)} · ${esc(n.mac_address)}</small></span></div>`).join("")||'<p class="muted">ไม่มีข้อมูล</p>';
    const software=item.software.map(s=>`<div class="software-row"><b>${esc(s.name)}</b><span>${esc(s.version||"-")}</span><span>${esc(s.publisher||"-")}</span></div>`).join("")||'<div class="empty">ไม่มีข้อมูลโปรแกรม</div>';
    const edit=state.user.role==="admin"?`<form id="assetEditForm" class="form-grid"><label>ชื่อเรียกเครื่อง<input id="editDisplayName" value="${esc(item.display_name)}" placeholder="เช่น เครื่องห้องบัตร 1"></label><label>รหัสทรัพย์สิน<input id="editAssetTag" value="${esc(item.asset_tag)}"></label><label>หน่วยงาน<select id="editDepartment">${departmentOptions(item.department)}</select></label><button class="primary">บันทึกทะเบียน</button></form>`:"";
    const lifecycle=item.retired?`<div class="lifecycle-banner"><b>เลิกใช้งานเมื่อ ${fmtDate(item.retired_at)}</b><span>${esc(item.retired_reason||"ไม่ระบุเหตุผล")}${item.online?" · Agent ยังออนไลน์อยู่ ต้องหยุดหรือลบ Agent ก่อนลบถาวร":""}</span></div>`:"";
    const lifecycleActions=state.user.role!=="admin"?"":item.retired?`<section class="detail-section lifecycle-actions"><h3>จัดการเครื่องที่เลิกใช้งาน</h3><div class="action-row"><button id="restoreAsset" type="button" class="secondary">นำกลับมาใช้งาน</button></div><form id="deleteAssetForm" class="danger-panel"><b>ลบถาวร</b><p>ลบทะเบียนและข้อมูล inventory ทั้งหมด ทำได้เมื่อเครื่องออฟไลน์เท่านั้น</p><label>รหัสผ่าน Admin<input id="deleteAdminPassword" type="password" autocomplete="current-password" required></label><label>พิมพ์ DELETE เพื่อยืนยัน<input id="deleteConfirmation" required></label><button class="danger-button" type="submit">ลบถาวร</button></form></section>`:`<form id="retireAssetForm" class="detail-section lifecycle-actions"><h3>เลิกใช้งานเครื่องนี้</h3><label>เหตุผล<input id="retireReason" maxlength="500" placeholder="เช่น เครื่องเสีย / ลง Windows ใหม่"></label><button class="secondary" type="submit">เลิกใช้งาน</button></form>`;
    $("assetDetail").innerHTML=`${lifecycle}<div class="detail-grid"><div class="detail-card"><span>Hostname</span><b>${esc(item.hostname)}</b></div><div class="detail-card"><span>Machine ID</span><b>${esc(item.machine_id)}</b></div><div class="detail-card"><span>Agent Version</span><b>${item.agent_version?`v${esc(item.agent_version)}`:"-"}</b></div><div class="detail-card"><span>Inventory ล่าสุด</span><b>${fmtDate(item.last_inventory_at)}</b></div><div class="detail-card"><span>OS</span><b>${esc(item.os_name)} ${esc(item.os_version)}</b></div><div class="detail-card"><span>CPU</span><b>${esc(item.cpu_name)} (${item.cpu_cores} cores)</b></div><div class="detail-card"><span>RAM</span><b>${fmtBytes(item.ram_used_bytes)} / ${fmtBytes(item.ram_total_bytes)}</b></div><div class="detail-card"><span>ผู้ผลิต</span><b>${esc(item.manufacturer||"-")}</b></div><div class="detail-card"><span>รุ่นเครื่อง</span><b>${esc(item.model||"-")}</b></div><div class="detail-card"><span>BIOS Serial Number</span><b>${esc(item.bios_serial||"-")}</b></div><div class="detail-card"><span>System UUID</span><b>${esc(item.system_uuid||"-")}</b></div><div class="detail-card"><span>ผู้ผลิตเมนบอร์ด</span><b>${esc(item.baseboard_manufacturer||"-")}</b></div><div class="detail-card"><span>รุ่นเมนบอร์ด</span><b>${esc(item.baseboard_product||"-")}</b></div><div class="detail-card"><span>Serial เมนบอร์ด</span><b>${esc(item.baseboard_serial||"-")}</b></div></div>${edit}${lifecycleActions}<div class="two-col detail-section"><div><h3>ดิสก์</h3>${disks}</div><div><h3>เครือข่าย</h3>${network}</div></div><div class="detail-section"><h3>โปรแกรมที่ติดตั้ง (${item.software.length})</h3><div class="software-list">${software}</div></div>`;
    $("assetDialog").showModal();
    $("assetEditForm")?.addEventListener("submit",async event=>{event.preventDefault();try{await api(`/api/ui/assets/${id}`,{method:"PATCH",body:JSON.stringify({display_name:$("editDisplayName").value.trim(),asset_tag:$("editAssetTag").value.trim(),department:$("editDepartment").value})});toast("บันทึกทะเบียนแล้ว");$("assetDialog").close();await refreshAssets();}catch(error){toast(error.message,true);}});
    $("retireAssetForm")?.addEventListener("submit",async event=>{event.preventDefault();try{await api(`/api/ui/assets/${id}/retire`,{method:"POST",body:JSON.stringify({reason:$("retireReason").value.trim()})});toast("ย้ายเครื่องไปยังรายการเลิกใช้งานแล้ว");$("assetDialog").close();await refreshAssets();}catch(error){toast(error.message,true);}});
    $("restoreAsset")?.addEventListener("click",async()=>{try{await api(`/api/ui/assets/${id}/restore`,{method:"POST",body:"{}"});toast("นำเครื่องกลับมาใช้งานแล้ว");$("assetDialog").close();await refreshAssets();}catch(error){toast(error.message,true);}});
    $("deleteAssetForm")?.addEventListener("submit",async event=>{event.preventDefault();if(!confirm("ลบทะเบียนเครื่องและข้อมูล inventory นี้ถาวรหรือไม่?"))return;try{await api(`/api/ui/assets/${id}`,{method:"DELETE",body:JSON.stringify({admin_password:$("deleteAdminPassword").value,confirmation:$("deleteConfirmation").value.trim()})});toast("ลบเครื่องถาวรแล้ว");$("assetDialog").close();await refreshAssets();}catch(error){toast(error.message,true);}});
  } catch(error){toast(error.message,true);}
}
$("closeDialog").addEventListener("click",()=>$("assetDialog").close());

$("policyScope").addEventListener("change",()=>$("policyValue").disabled=$("policyScope").value==="global");
$("policyForm").addEventListener("submit",async event=>{event.preventDefault();const payload={scope_type:$("policyScope").value,scope_value:$("policyValue").value.trim(),heartbeat_seconds:Number($("heartbeatSeconds").value),online_threshold_seconds:Number($("onlineSeconds").value),boot_delay_seconds:Number($("bootDelay").value),daily_enabled:$("dailyEnabled").checked,daily_time:$("dailyTime").value};try{await api("/api/ui/policies",{method:"PUT",body:JSON.stringify(payload)});toast("บันทึกนโยบายแล้ว");await loadControl();}catch(error){toast(error.message,true);}});
function updateCampaignTarget(){const type=$("campaignType").value;$("campaignDepartmentLabel").classList.toggle("hidden",type!=="department");$("campaignDepartment").disabled=type!=="department";$("campaignAssetLabel").classList.toggle("hidden",type!=="asset");$("campaignValue").disabled=type!=="asset";}
$("campaignType").addEventListener("change",updateCampaignTarget);
$("campaignForm").addEventListener("submit",async event=>{event.preventDefault();try{const type=$("campaignType").value,value=type==="department"?$("campaignDepartment").value:type==="asset"?$("campaignValue").value.trim():"";await api("/api/ui/campaigns",{method:"POST",body:JSON.stringify({target_type:type,target_value:value})});toast("สร้างคำขอเก็บข้อมูลแล้ว");await loadControl();}catch(error){toast(error.message,true);}});

async function loadControl(){
  try {
    const [policies,campaigns]=await Promise.all([api("/api/ui/policies"),api("/api/ui/campaigns")]); state.policies=policies.items;
    const global=policies.items.find(p=>p.scope_type==="global");if(global){$("heartbeatSeconds").value=global.heartbeat_seconds;$("onlineSeconds").value=global.online_threshold_seconds;$("bootDelay").value=global.boot_delay_seconds;$("dailyEnabled").checked=global.daily_enabled;$("dailyTime").value=global.daily_time;}
    $("campaignList").innerHTML=campaigns.items.map(c=>`<div class="list-item"><span><b>#${c.id} · ${esc(c.target_type)} ${esc(c.target_value)}</b><small>${fmtDate(c.created_at)} · ${c.completed}/${c.delivered} เสร็จ</small></span></div>`).join("")||'<p class="muted">ยังไม่มีคำขอ</p>';
  } catch(error){toast(error.message,true);}
}

$("departmentForm").addEventListener("submit",async event=>{event.preventDefault();try{
  await api("/api/ui/departments",{method:"POST",body:JSON.stringify({name:$("departmentName").value.trim()})});
  $("departmentName").value="";toast("เพิ่มหน่วยงานแล้ว");await loadSettings();
}catch(error){toast(error.message,true);}});

$("wallpaperForm").addEventListener("submit",async event=>{event.preventDefault();try{
  const file=$("wallpaperFile").files[0];if(!file)throw new Error("กรุณาเลือกรูปภาพ");
  if(!["image/jpeg","image/png"].includes(file.type))throw new Error("รองรับเฉพาะ JPG หรือ PNG");
  if(file.size<1||file.size>10*1024*1024)throw new Error("ไฟล์ต้องมีขนาดไม่เกิน 10 MB");
  const response=await fetch("/api/ui/wallpaper",{method:"POST",credentials:"same-origin",headers:{"Content-Type":file.type,"X-CSRF-Token":state.csrf},body:await file.arrayBuffer()});
  const body=await response.json();if(!response.ok)throw new Error(body.detail||`HTTP ${response.status}`);
  $("wallpaperFile").value="";toast("อัปโหลดแล้ว Agent จะรับภาพใน heartbeat รอบถัดไป");await loadSettings();
}catch(error){toast(error.message,true);}});

$("disableWallpaper").addEventListener("click",async()=>{if(!confirm("ยกเลิกการบังคับภาพพื้นหลังทุกเครื่องหรือไม่?"))return;try{
  await api("/api/ui/wallpaper",{method:"DELETE"});toast("ยกเลิกนโยบายภาพพื้นหลังแล้ว");await loadSettings();
}catch(error){toast(error.message,true);}});

let wallpaperExclusionSearchTimer;
$("wallpaperExclusionSearch").addEventListener("input",()=>{
  clearTimeout(wallpaperExclusionSearchTimer);
  wallpaperExclusionSearchTimer=setTimeout(()=>loadWallpaperExclusions(),300);
});

function renderWallpaperExclusions(data){
  $("wallpaperExclusionCount").textContent=`${Number(data.total||0)} เครื่อง`;
  $("wallpaperExclusionList").innerHTML=data.items.map(item=>`<div class="list-item"><span><b>${esc(item.display_name||item.asset_tag||item.hostname)}</b><small>${esc(item.hostname)}${item.asset_tag?` · ${esc(item.asset_tag)}`:""}${item.department?` · ${esc(item.department)}`:""}<br>${item.reason?`เหตุผล: ${esc(item.reason)} · `:""}เพิ่มโดย ${esc(item.created_by)} · ${fmtDate(item.created_at)}</small></span>${state.user.role==="admin"?`<button class="ghost wallpaper-exclusion-remove" data-id="${item.asset_id}">นำออก</button>`:""}</div>`).join("")||'<p class="muted">ยังไม่มีเครื่องที่ยกเว้น</p>';
  const search=$("wallpaperExclusionSearch").value.trim();
  $("wallpaperExclusionResults").innerHTML=data.candidates.length?data.candidates.map(item=>`<div class="list-item"><span><b>${esc(item.display_name||item.asset_tag||item.hostname)}</b><small>${esc(item.hostname)}${item.asset_tag?` · ${esc(item.asset_tag)}`:""}${item.department?` · ${esc(item.department)}`:""}</small></span><button class="secondary wallpaper-exclusion-add" data-id="${item.asset_id}">ยกเว้น</button></div>`).join(""):search?'<p class="muted">ไม่พบเครื่องที่เพิ่มได้</p>':'<p class="muted">พิมพ์เพื่อค้นหาเครื่องที่กำลังใช้งาน</p>';
  document.querySelectorAll(".wallpaper-exclusion-add").forEach(button=>button.addEventListener("click",async()=>{try{
    await api("/api/ui/wallpaper/exclusions",{method:"POST",body:JSON.stringify({asset_id:Number(button.dataset.id),reason:$("wallpaperExclusionReason").value.trim()})});
    $("wallpaperExclusionSearch").value="";$("wallpaperExclusionReason").value="";toast("เพิ่มเครื่องในรายการยกเว้นแล้ว");await loadSettings();
  }catch(error){toast(error.message,true);}}));
  document.querySelectorAll(".wallpaper-exclusion-remove").forEach(button=>button.addEventListener("click",async()=>{if(!confirm("นำเครื่องนี้ออกจากรายการยกเว้นและให้กลับมารับภาพส่วนกลางหรือไม่?"))return;try{
    await api(`/api/ui/wallpaper/exclusions/${button.dataset.id}`,{method:"DELETE"});toast("นำเครื่องออกจากรายการยกเว้นแล้ว");await loadSettings();
  }catch(error){toast(error.message,true);}}));
}

async function loadWallpaperExclusions(){
  const serial=++state.wallpaperExclusionRequestSerial;
  const search=$("wallpaperExclusionSearch").value.trim();
  try{const data=await api(`/api/ui/wallpaper/exclusions?search=${encodeURIComponent(search)}`);if(serial!==state.wallpaperExclusionRequestSerial)return;renderWallpaperExclusions(data);}catch(error){toast(error.message,true);}
}

async function loadSettings(){
  try{
    const search=$("wallpaperExclusionSearch").value.trim();
    const [departments,wallpaper,exclusions]=await Promise.all([api("/api/ui/departments"),api("/api/ui/wallpaper"),api(`/api/ui/wallpaper/exclusions?search=${encodeURIComponent(search)}`)]);
    state.departments=departments.items.filter(item=>item.enabled).map(item=>item.name);
    const departmentHtml='<option value="">เลือกหน่วยงาน</option>'+state.departments.map(d=>`<option value="${esc(d)}">${esc(d)}</option>`).join("");
    $("policyValue").innerHTML=departmentHtml;$("campaignDepartment").innerHTML=departmentHtml;
    $("departmentList").innerHTML=departments.items.map(item=>`<div class="list-item department-row" data-department-id="${item.id}"><span><b>${esc(item.name)}</b><small>${item.asset_count} เครื่อง · ${item.enabled?"เปิดใช้งาน":"ปิดใช้งาน"}</small></span><span class="row-actions"><button class="secondary department-edit" data-id="${item.id}" data-name="${esc(item.name)}">แก้ชื่อ</button><button class="ghost department-toggle" data-id="${item.id}" data-enabled="${item.enabled?0:1}">${item.enabled?"ปิด":"เปิด"}</button></span></div>`).join("")||'<p class="muted">ยังไม่มีหน่วยงาน</p>';
    document.querySelectorAll(".department-toggle").forEach(button=>button.addEventListener("click",async()=>{try{
      await api(`/api/ui/departments/${button.dataset.id}`,{method:"PATCH",body:JSON.stringify({enabled:Boolean(Number(button.dataset.enabled))})});await loadSettings();
    }catch(error){toast(error.message,true);}}));
    document.querySelectorAll(".department-edit").forEach(button=>button.addEventListener("click",()=>{
      const row=document.querySelector(`[data-department-id="${button.dataset.id}"]`);if(!row)return;
      row.innerHTML=`<form class="inline-form department-rename-form" data-id="${button.dataset.id}"><input class="department-rename-input" value="${esc(button.dataset.name)}" required maxlength="200"><button class="primary" type="submit">บันทึก</button><button class="ghost department-rename-cancel" type="button">ยกเลิก</button></form>`;
      row.querySelector(".department-rename-cancel").addEventListener("click",()=>loadSettings());
      row.querySelector(".department-rename-form").addEventListener("submit",async event=>{event.preventDefault();try{const name=row.querySelector(".department-rename-input").value.trim();await api(`/api/ui/departments/${button.dataset.id}/name`,{method:"PUT",body:JSON.stringify({name})});toast("เปลี่ยนชื่อหน่วยงานแล้ว");await refreshAssets();await loadSettings();}catch(error){toast(error.message,true);}});
      row.querySelector(".department-rename-input").focus();
    }));
    const statuses=wallpaper.statuses||{},summary=Object.entries(statuses).map(([name,total])=>`${esc(name||"pending")}: ${total}`).join(" · ")||"ยังไม่มี Agent รายงานสถานะ";
    const excluded=`ยกเว้น ${Number(wallpaper.excluded_count||0)} เครื่อง`;
    $("wallpaperCurrent").innerHTML=wallpaper.enabled?`<img src="${esc(wallpaper.image_url)}" alt="ภาพพื้นหลังปัจจุบัน"><b>กำลังบังคับใช้ทุกเครื่องที่ไม่ถูกยกเว้น</b><small>อัปเดต ${fmtDate(wallpaper.updated_at)} · ${excluded} · ${summary}</small>`:`<span>ยังไม่ได้บังคับภาพพื้นหลัง</span><small>${excluded} · ${summary}</small>`;
    $("disableWallpaper").classList.toggle("hidden",!wallpaper.enabled);
    renderWallpaperExclusions(exclusions);
  }catch(error){toast(error.message,true);}
}

$("apiKeyForm").addEventListener("submit",async event=>{event.preventDefault();try{const data=await api("/api/ui/api-keys",{method:"POST",body:JSON.stringify({name:$("apiKeyName").value.trim()})});$("newKey").textContent=`บันทึกคีย์นี้ทันที (จะแสดงครั้งเดียว): ${data.api_key}`;$("newKey").classList.remove("hidden");$("apiKeyName").value="";await loadAccess();}catch(error){toast(error.message,true);}});
$("userForm").addEventListener("submit",async event=>{event.preventDefault();try{await api("/api/ui/users",{method:"POST",body:JSON.stringify({username:$("newUsername").value.trim(),password:$("newPassword").value,role:$("newRole").value})});toast("เพิ่มผู้ใช้แล้ว");$("newUsername").value="";$("newPassword").value="";await loadAccess();}catch(error){toast(error.message,true);}});

async function loadAccess(){
  try {
    const [keys,users]=await Promise.all([api("/api/ui/api-keys"),api("/api/ui/users")]);
    $("apiKeyList").innerHTML=keys.items.map(k=>`<div class="list-item"><span><b>${esc(k.name)}</b><small>${esc(k.key_prefix)}… · ${k.enabled?"ใช้งาน":"ปิด"} · ใช้ล่าสุด ${fmtDate(k.last_used_at)}</small></span><span><button class="ghost key-toggle" data-id="${k.id}" data-enabled="${k.enabled?0:1}">${k.enabled?"ปิด":"เปิด"}</button> <button class="secondary key-rotate" data-id="${k.id}">หมุนคีย์</button></span></div>`).join("")||'<p class="muted">ยังไม่มี API key</p>';
    $("userList").innerHTML=users.items.map(u=>`<div class="list-item"><span><b>${esc(u.username)}</b><small>${esc(u.role)} · ${u.enabled?"ใช้งาน":"ปิด"}</small></span></div>`).join("");
    document.querySelectorAll(".key-toggle").forEach(b=>b.addEventListener("click",async()=>{try{await api(`/api/ui/api-keys/${b.dataset.id}`,{method:"PATCH",body:JSON.stringify({enabled:Boolean(Number(b.dataset.enabled))})});await loadAccess();}catch(error){toast(error.message,true);}}));
    document.querySelectorAll(".key-rotate").forEach(b=>b.addEventListener("click",async()=>{if(!confirm("คีย์เดิมจะใช้ไม่ได้ทันที ต้องการหมุนคีย์หรือไม่?"))return;try{const data=await api(`/api/ui/api-keys/${b.dataset.id}/rotate`,{method:"POST"});$("newKey").textContent=`บันทึกคีย์นี้ทันที (จะแสดงครั้งเดียว): ${data.api_key}`;$("newKey").classList.remove("hidden");await loadAccess();}catch(error){toast(error.message,true);}}));
  } catch(error){toast(error.message,true);}
}

$("agentRolloutType").addEventListener("change",()=>{
  const type=$("agentRolloutType").value;
  $("agentRolloutDepartmentLabel").classList.toggle("hidden",type!=="department");
  $("agentRolloutDepartment").disabled=type!=="department";
  $("agentRolloutAssetLabel").classList.toggle("hidden",type!=="asset");
  $("agentRolloutAsset").disabled=type!=="asset";
});

$("agentReleaseForm").addEventListener("submit",async event=>{event.preventDefault();try{
  const file=$("agentReleaseBundle").files[0];if(!file)throw new Error("กรุณาเลือกไฟล์ .hmagent");
  if(file.size>50*1024*1024)throw new Error("ไฟล์ Agent release ใหญ่เกิน 50 MB");
  const response=await fetch("/api/ui/agent-updates/releases",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/octet-stream","X-CSRF-Token":state.csrf,"X-Admin-Password":$("agentReleasePassword").value},body:await file.arrayBuffer()});
  const body=await response.json();if(!response.ok)throw new Error(body.detail||`HTTP ${response.status}`);
  $("agentReleasePassword").value="";$("agentReleaseBundle").value="";toast(`นำเข้า Agent v${body.version} แล้ว`);await loadAgentUpdates();
}catch(error){toast(error.message,true);}});

$("agentRolloutForm").addEventListener("submit",async event=>{event.preventDefault();try{
  const type=$("agentRolloutType").value;
  const value=type==="department"?$("agentRolloutDepartment").value:type==="asset"?$("agentRolloutAsset").value.trim():"";
  await api("/api/ui/agent-updates/rollouts",{method:"POST",body:JSON.stringify({release_id:Number($("agentReleaseSelect").value),target_type:type,target_value:value,admin_password:$("agentRolloutPassword").value,confirmation:$("agentRolloutConfirmation").value})});
  $("agentRolloutPassword").value="";$("agentRolloutConfirmation").value="";toast("ส่งคำสั่งอัปเดต Agent แล้ว");await loadAgentUpdates();
}catch(error){toast(error.message,true);}});

async function loadAgentUpdates(){
  try{
    const data=await api("/api/ui/agent-updates");
    $("agentReleaseSelect").innerHTML=data.releases.length?data.releases.filter(item=>item.enabled).map(item=>`<option value="${item.id}">v${esc(item.version)} · ${fmtDate(item.uploaded_at)}</option>`).join(""):'<option value="">ยังไม่มี release</option>';
    $("agentRolloutDepartment").innerHTML='<option value="">เลือกหน่วยงาน</option>'+state.departments.map(name=>`<option value="${esc(name)}">${esc(name)}</option>`).join("");
    const target={all:"ทุกเครื่อง",department:"หน่วยงาน",asset:"Asset ID"};
    $("agentRolloutList").innerHTML=data.rollouts.map(item=>`<div class="list-item"><span><b>Agent v${esc(item.version)} · ${target[item.target_type]||esc(item.target_type)}${item.target_value?` ${esc(item.target_value)}`:""}</b><small>${fmtDate(item.created_at)} · โดย ${esc(item.created_by)} · หมดอายุ ${fmtDate(item.expires_at)}</small></span><span><span class="status-pill completed">สำเร็จ ${Number(item.applied||0)}</span> <span class="status-pill pending">รอ ${Number(item.pending||0)}</span> <span class="status-pill failed">ล้มเหลว ${Number(item.failed||0)}</span> <small>รับคำสั่ง ${Number(item.delivered||0)}</small></span></div>`).join("")||'<p class="muted">ยังไม่มีคำสั่งอัปเดต Agent</p>';
  }catch(error){toast(error.message,true);}
}

function renderUpdateStatus(data){
  state.version=data.current_version||state.version; $("updateCurrentVersion").textContent=`v${state.version||"-"}`; $("currentVersion").textContent=`Server v${state.version||"-"}`;
  const labels={idle:"พร้อมใช้งาน",pending:"รอติดตั้ง",installing:"กำลังติดตั้ง",completed:"ติดตั้งสำเร็จ",failed:"ติดตั้งไม่สำเร็จ",unknown:"ไม่ทราบสถานะ"};
  $("updateStateText").textContent=labels[data.status]||data.status||"พร้อมใช้งาน";
}

async function loadUpdates(){
  try {
    const [config,status,history]=await Promise.all([api("/api/ui/updates/config"),api("/api/ui/updates/status"),api("/api/ui/updates/history")]);
    $("updateEnabled").checked=config.enabled; $("updateRetention").value=config.backup_retention;
    $("updateTrust").textContent=config.public_key_available?"พบ public key สำหรับตรวจลายเซ็น · Service: "+config.server_service_name:"ไม่พบ update_public.pem — ยังติดตั้ง release อย่างปลอดภัยไม่ได้";
    renderUpdateStatus(status); renderUpdateHistory(history.items);
  } catch(error){toast(error.message,true);}
}

function renderUpdateHistory(items){
  $("updateHistory").innerHTML=items.map(item=>`<div class="list-item"><span><b>${esc(item.action==="rollback"?"ย้อนกลับ":"อัปเดต")} v${esc(item.from_version)} → v${esc(item.to_version)}</b><small>${fmtDate(item.started_at)} · โดย ${esc(item.started_by||"system")}${item.error_message?` · ${esc(item.error_message)}`:""}</small></span><span><span class="status-pill ${esc(item.status)}">${esc(item.status)}</span> ${item.status==="completed"&&item.backup_path?`<button class="ghost rollback-update" data-id="${item.id}">ย้อนกลับ</button>`:""}</span></div>`).join("")||'<p class="muted">ยังไม่มีประวัติอัปเดต</p>';
  document.querySelectorAll(".rollback-update").forEach(button=>button.addEventListener("click",async()=>{
    const password=prompt("รหัสผ่าน Admin สำหรับย้อนกลับ"); if(!password)return;
    const confirmation=prompt("พิมพ์ ROLLBACK เพื่อยืนยัน"); if(confirmation!=="ROLLBACK"){toast("ยกเลิก: คำยืนยันไม่ถูกต้อง",true);return;}
    try{await api("/api/ui/updates/rollback",{method:"POST",body:JSON.stringify({update_id:Number(button.dataset.id),admin_password:password,confirmation})});toast("ส่งคำขอย้อนกลับแล้ว ระบบจะหยุดชั่วคราว");startUpdatePolling();}catch(error){toast(error.message,true);}
  }));
}

$("updateConfigForm").addEventListener("submit",async event=>{event.preventDefault();try{
  await api("/api/ui/updates/config",{method:"PUT",body:JSON.stringify({enabled:$("updateEnabled").checked,backup_retention:Number($("updateRetention").value),admin_password:$("updateConfigPassword").value})});
  $("updateConfigPassword").value="";toast("บันทึกแหล่งอัปเดตแล้ว");await loadUpdates();
}catch(error){toast(error.message,true);}});

$("installUpdateForm").addEventListener("submit",async event=>{event.preventDefault();try{
  const file=$("updateBundle").files[0];if(!file)throw new Error("กรุณาเลือกไฟล์ .hmrelease");
  if(file.size>210*1024*1024)throw new Error("ไฟล์ release ใหญ่เกิน 210 MB");
  const response=await fetch("/api/ui/updates/import",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/octet-stream","X-CSRF-Token":state.csrf,"X-Admin-Password":$("installPassword").value,"X-Update-Confirmation":$("installConfirmation").value},body:await file.arrayBuffer()});
  const body=await response.json();if(!response.ok)throw new Error(body.detail||`HTTP ${response.status}`);
  $("installPassword").value="";$("installConfirmation").value="";$("updateBundle").value="";toast("ตรวจลายเซ็นและเตรียมไฟล์แล้ว ระบบจะเริ่มอัปเดต");startUpdatePolling();
}catch(error){toast(error.message,true);}});

function startUpdatePolling(){
  clearInterval(startUpdatePolling.timer);let failures=0;
  startUpdatePolling.timer=setInterval(async()=>{try{const data=await api("/api/ui/updates/status");failures=0;renderUpdateStatus(data);if(data.status==="completed"||data.status==="failed"){clearInterval(startUpdatePolling.timer);await bootstrap();}}catch(_){failures++;$("updateStateText").textContent="Server กำลังเริ่มใหม่…";if(failures>60)clearInterval(startUpdatePolling.timer);}},3000);
}

bootstrap();
