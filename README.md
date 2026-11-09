# HosMonitor Server 1.0.9 / Agent 1.0.10

ระบบ IT Asset Monitoring แบบ on-premise สำหรับ Windows ไม่เกิน 300 เครื่อง มี Web Dashboard, REST API, SQLite และ Agent แบบ Windows Service ไม่มี license, activation, trial, remote shell หรือการเชื่อมต่อออกอินเทอร์เน็ต

## ไฟล์ที่ใช้ติดตั้งจริง

- เครื่องแม่รุ่นที่ใช้งานปัจจุบัน: `release-output\v1.0.9\HosMonitorServerSetup-1.0.9.exe`
- เครื่อง Agent รุ่นที่ใช้งานปัจจุบัน: `release-output\v1.0.10\HosMonitorAgentSetup-1.0.10.exe`
- อัปเดต Server ในอนาคต: `release-output\vX.Y.Z\HosMonitorServer-X.Y.Z.hmrelease`
- อัปเดต Agent ในอนาคต: `release-output\vX.Y.Z\HosMonitorAgent-X.Y.Z.hmagent`

ผู้ใช้เครื่องแม่และเครื่อง Agent ไม่ต้องติดตั้ง Python ไม่ต้องเปิด PowerShell และไม่ต้องแก้ config เอง

## ติดตั้งเครื่องแม่จากศูนย์

1. คัดลอก `HosMonitorServerSetup-1.0.9.exe` ไปเครื่องแม่
2. ดับเบิลคลิกไฟล์และกด **Yes** ที่ UAC
3. ตัวติดตั้งจะหยุดและถอน Services รุ่นเดิม, สำรองโปรแกรมเดิม, ติดตั้ง Server/Updater, เปิด Firewall TCP 6001 เฉพาะเครือข่ายภายใน RFC1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) และเริ่ม Services อัตโนมัติ
4. เมื่อติดตั้งสำเร็จ Browser จะเปิด `http://127.0.0.1:6001`
5. ครั้งแรกให้สร้างบัญชี Admin จากหน้าเว็บบนเครื่องแม่
6. เครื่องอื่นใน VLAN เปิด `http://<IP-เครื่องแม่>:6001`

Services ที่ติดตั้ง:

- `HosMonitorServer` — Web Dashboard/API ทำงานเป็น LocalService
- `HosMonitorUpdater` — ติดตั้ง signed Server release และ rollback ทำงานเป็น LocalSystem

หลังติดตั้ง โปรแกรม `HosMonitorServerControl.exe` จะแสดงหน้าสถานะ Server/Updater, รุ่น, IP/พอร์ต และจำนวน Agent กดกากบาทแล้วหน้าต่างจะซ่อนไปที่ System Tray โดย Services ยังทำงาน คลิกขวาที่ไอคอนเพื่อเปิดหน้าควบคุม, เปิด Dashboard, เริ่มระบบ หรือ “หยุดและปิดระบบ” ได้ หน้าควบคุมจะเริ่มที่ Tray อัตโนมัติเมื่อผู้ดูแลเข้าสู่ Windows

ตัวติดตั้งสร้าง Shortcut บน Desktop สาธารณะ 2 รายการ คือ `HosMonitor Server Control` สำหรับเปิดหน้าควบคุม และ `HosMonitor Dashboard` สำหรับเปิดหน้าเว็บโดยตรง ภายในหน้าควบคุมมีปุ่ม **เปิดหน้าเว็บ Dashboard** เช่นกัน

โปรแกรมอยู่ที่ `C:\Program Files\HosMonitor Server` ข้อมูลอยู่ที่ `C:\ProgramData\HosMonitorServer` ระบบเริ่มอัตโนมัติพร้อม Windows ไม่ต้องเปิดหน้าต่าง Console ค้างไว้

Log ของ Windows Services อยู่ที่ `C:\ProgramData\HosMonitorServer\logs` เพื่อให้บัญชี `LocalService` เขียนได้โดยไม่ต้องให้สิทธิ์แก้ไขไฟล์โปรแกรม

การติดตั้งทับจะรักษา `config.yaml`, SQLite, บัญชี Admin, Agent token และข้อมูลเดิมไว้ ไม่ลบฐานข้อมูลอัตโนมัติ หากติดตั้งล้มเหลวจะคืนโปรแกรมและ config/token เดิมจาก backup สำหรับเครื่องแม่ใหม่ที่ยังไม่มี config ตัวติดตั้งจะใช้ token ที่ build คู่กับ Agent Setup เท่านั้น

## ติดตั้ง Agent ครั้งแรก

1. คัดลอก `HosMonitorAgentSetup-1.0.10.exe` ไปเครื่องลูก
2. ดับเบิลคลิกและกด **Yes** ที่ UAC
3. รอข้อความ “ติดตั้งเรียบร้อย” เท่านั้น

ตัวติดตั้งฝัง URL เครื่องแม่และ shared Agent token ไว้แล้ว ติดตั้งสอง Services อัตโนมัติ:

- `HosMonitorAgent` — heartbeat/inventory ทำงานเป็น LocalService
- `HosMonitorAgentUpdater` — ตรวจลายเซ็น ติดตั้ง และ rollback Agent ทำงานเป็น LocalSystem

ไฟล์โปรแกรมอยู่ที่ `C:\Program Files\HosMonitor Agent` ส่วน identity, config, log และ update state อยู่ที่ `C:\ProgramData\HosMonitor` การติดตั้งทับรักษา machine ID, Asset Tag และ Department เดิมไว้

เครื่อง Agent ที่ติดตั้งจากรุ่นเก่าซึ่งยังไม่มี Agent Updater ต้องนำ Setup EXE รุ่นปัจจุบันไปติดตั้งทับหนึ่งครั้ง หลังจากนั้น Admin จึงสั่งอัปเดตจาก Dashboard ได้ทั้งหมด

## จัดการเครื่องที่ไม่ใช้งานแล้ว

หน้า **ทะเบียนเครื่อง** ค้นหาอัตโนมัติขณะพิมพ์และกรองตามหน่วยงาน สถานะออนไลน์ และสถานะการใช้งานได้ ตารางทะเบียน หน้ารายละเอียด และไฟล์ CSV แสดงเวอร์ชัน Agent ของแต่ละเครื่อง; เครื่องที่ยังไม่เคยรายงานเวอร์ชันจะแสดง `-` เครื่องที่เสีย ลง Windows ใหม่ หรือเลิกใช้งาน ให้เปิดรายละเอียดแล้วเลือก **เลิกใช้งาน** พร้อมบันทึกเหตุผล รายการจะถูกซ่อนจาก Dashboard และสถิติหลัก แต่ยังดูย้อนหลังได้ด้วยตัวกรอง **เลิกใช้งานแล้ว**

เครื่องที่เลิกใช้งานจะไม่รับคำสั่งเก็บข้อมูล ภาพพื้นหลัง หรืออัปเดต Agent หาก Agent ยังส่ง heartbeat ระบบจะแสดงว่าเครื่องนั้นยังออนไลน์และจะไม่อนุญาตให้ลบถาวร ให้หยุดหรือถอน Agent ก่อน

Admin สามารถ **นำกลับมาใช้งาน** ได้โดยไม่เสียประวัติ ส่วน **ลบถาวร** ต้องให้เครื่องออฟไลน์ ยืนยันรหัสผ่าน Admin และพิมพ์ `DELETE` การลบจะนำทะเบียน inventory, disk, network, software และประวัติ monitor ที่ผูกกับเครื่องออกทั้งหมด

## จัดการหน่วยงานและภาพพื้นหลัง

หน้า **ตั้งค่า Agent** ให้ Admin กด **แก้ชื่อ** ที่หน่วยงาน บันทึก หรือยกเลิกได้ การเปลี่ยนชื่อจะปรับทะเบียนเครื่องทั้งที่ใช้งาน/เลิกใช้ นโยบาย คำขอเก็บข้อมูล และ Agent rollout พร้อมกัน ชื่อเดิมถูกเก็บเป็น alias ดังนั้น Agent รุ่นเก่าที่ยังรายงานชื่อเดิมจะถูก map กลับไปยังชื่อใหม่โดยอัตโนมัติ

ส่วน **ภาพพื้นหลังทุกเครื่อง** มีรายการ **เครื่องที่ละเว้นการเปลี่ยนภาพ** พิมพ์ค้นหาจากชื่อเรียกเครื่อง, Hostname, Asset Tag หรือ Machine ID ได้ทันที เครื่องที่ยกเว้นจะหยุดบังคับและปลดล็อกให้ผู้ใช้เปลี่ยนภาพเอง เมื่อนำออกจะกลับมารับภาพส่วนกลางใน heartbeat ถัดไป ระบบไม่คืนภาพก่อนใช้งาน HosMonitor อัตโนมัติ เพราะ Agent ไม่ได้สำรองภาพเดิมไว้

## สั่งอัปเดต Agent จาก Admin

1. เครื่องพัฒนาสร้าง `.hmagent` รุ่นใหม่
2. เข้า Dashboard เครื่องแม่ > **อัปเดต Agent**
3. อัปโหลดไฟล์ `.hmagent` และยืนยันรหัสผ่าน Admin
4. เลือกรุ่นและเป้าหมาย: ทุกเครื่อง, หน่วยงาน หรือ Asset ID
5. พิมพ์ `UPDATE AGENT` แล้วกดสั่งอัปเดต
6. ดูจำนวนรับคำสั่ง/รอ/สำเร็จ/ล้มเหลวในหน้าเดียวกัน

คำสั่ง rollout มีอายุ 7 วัน เครื่องที่ออฟไลน์จะรับคำสั่งอัตโนมัติเมื่อกลับมา heartbeat ภายในช่วงนี้โดยไม่ต้องสั่งใหม่ หากเลยวันหมดอายุต้องสร้าง rollout ใหม่ เครื่องที่มีเวอร์ชันตรงกับรุ่นเป้าหมายแล้วจะถูกนับเป็น `applied` โดยไม่ดาวน์โหลด ติดตั้ง หรือ restart ซ้ำ

Agent ดาวน์โหลดผ่าน API ที่ต้องใช้ Agent token ตรวจขนาดและ SHA-256 ก่อน queue จากนั้น Updater ตรวจ RSA signature ซ้ำ อนุญาตให้เปลี่ยนเฉพาะ `HosMonitorAgent.ps1`, `HosMonitorWallpaper.ps1` และ `VERSION` เท่านั้น ไม่มีช่องให้ส่งคำสั่งหรือไฟล์อื่น หากเริ่มรุ่นใหม่ไม่ได้จะคืนไฟล์สำรองและเริ่ม Agent รุ่นเดิม

## Build บนเครื่องพัฒนา

เตรียม environment ครั้งแรก:

```powershell
Set-Location -LiteralPath "E:\MCH\งาน IT (เฉลิม)\Dev\hos_monitor"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

กุญแจลงลายเซ็นมีสองส่วน:

- `dev-secrets\update_private.pem` เก็บเฉพาะเครื่องพัฒนา ห้ามนำไปเครื่องแม่หรือ Agent
- `update_public.pem` รวมในตัวติดตั้งเพื่อใช้ตรวจลายเซ็น

สร้างตัวติดตั้งเครื่องแม่และ Agent เป็นคู่เดียวกัน (ใช้สำหรับเริ่มระบบใหม่):

```powershell
.\scripts\Build-FreshInstallers.ps1 -ServerUrl "http://192.168.111.65:6001"
```

คำสั่งนี้สร้าง deployment token แบบสุ่มและฝัง token เดียวกันใน EXE ทั้งคู่ โดยลบไฟล์ token ชั่วคราวหลัง build ให้ติดตั้ง Server ก่อนแล้วจึงติดตั้ง Agent เมื่อเครื่องแม่มี config เดิม ตัวติดตั้งจะรักษา token เดิมเพื่อไม่ให้ Agent ที่ใช้งานอยู่หลุด

หากต้องการ build Agent เพิ่มโดยใช้ token ปัจจุบันของเครื่องแม่:

```powershell
.\scripts\Build-AgentInstaller.ps1 -ServerUrl "http://192.168.111.65:6001" -ServerConfigPath ".\production-config.yaml"
```

หลัง build ให้ลบ `production-config.yaml` ออกจากเครื่องพัฒนาหากไม่จำเป็น เพราะมี shared Agent token

## อัปเดตในอนาคต

เพิ่มเลข `VERSION` สำหรับ Server และ `AGENT_VERSION` สำหรับ Agent เช่น `1.0.10`; เพิ่ม migration ใหม่ท้าย `server\migrations.py` เมื่อ schema เปลี่ยน ห้ามแก้ migration ที่เคยปล่อยแล้ว

Server release:

```powershell
.\scripts\Build-Server.ps1
.\scripts\Build-Release.ps1 -Version 1.0.1 -MinimumVersion 1.0.0
```

นำ `.hmrelease` ไป Dashboard > **อัปเดตระบบ** ใส่รหัสผ่าน Admin และพิมพ์ `UPDATE` เครื่องแม่ตรวจลายเซ็น สำรอง SQLite/โปรแกรม ติดตั้ง ตรวจ `/health` และ rollback อัตโนมัติเมื่อไม่สำเร็จ

Agent release:

```powershell
.\scripts\Build-AgentRelease.ps1 -Version 1.0.1
```

นำ `.hmagent` ไปหน้า **อัปเดต Agent** ตามขั้นตอนด้านบน

## ข้อมูลที่เก็บและการขยายระบบ

Agent ส่ง heartbeat ทุก 2 นาทีโดยค่าเริ่มต้น Online เมื่อ Server ได้รับภายใน 5 นาที Agent ที่ยังไม่เคยส่ง inventory จะเก็บและส่งครั้งแรกทันทีหลัง heartbeat สำเร็จ ส่วน boot ครั้งถัดไปใช้ delay 10 นาทีหรือตามนโยบาย, เวลาเก็บประจำวัน และ collection campaign ข้อมูลประกอบด้วย hostname, machine ID, asset tag, department, OS, CPU, RAM, fixed disks, IPv4 LAN, software แบบ system-wide จาก Registry, ผู้ผลิต/รุ่นจาก `Win32_ComputerSystem`, BIOS Serial, System UUID และผู้ผลิต/รุ่น/Serial ของเมนบอร์ดจาก `Win32_BaseBoard` โดยไม่ใช้ `Win32_Product`

ก่อนส่ง inventory Agent จะ trim/จำกัดความยาวให้ตรงกับ API, กรองรายการที่ไม่ถูกต้อง และ retry CIM สำคัญแบบจำกัดครั้ง หากรอบหนึ่งล้มเหลว heartbeat ยังทำงานและ inventory จะลองใหม่ในรอบถัดไป ดูชื่อ collector และสาเหตุได้จาก `C:\ProgramData\HosMonitor\agent.log` โดย log จะไม่บันทึก Agent token หรือ payload เต็ม

ค่า SMBIOS ที่ไม่มีความหมาย เช่น `To Be Filled By O.E.M.`, `Default String` และ `Unknown` จะไม่ถูกใช้เป็นข้อมูลยี่ห้อ/รุ่นและหน้าเว็บจะแสดง `-` แทน เครื่องประกอบบางรุ่นอาจไม่มีข้อมูลเหล่านี้ ขึ้นอยู่กับ BIOS/SMBIOS ของผู้ผลิต

monitor รุ่นแรกคือ `heartbeat` และ `inventory` ส่วน monitor ใหม่เพิ่มผ่าน contract `monitor_type`, `schema_version`, `observed_at`, `status`, `severity` และ JSON payload โดยไม่แก้ schema inventory หลัก

## Integration API

ระบบภายนอกใช้ API key แบบอ่านอย่างเดียวผ่าน header `X-API-Key`:

```http
GET /api/v1/assets?page=1&page_size=50&department=OPD&online=true
X-API-Key: hm_xxxxxxxxxxxxxxxxx
```

Endpoints:

- `GET /api/v1/assets`
- `GET /api/v1/assets/{id}`
- `GET /api/v1/monitor-types`
- `GET /openapi.json`

## ตรวจสอบและแก้ปัญหา

- Server setup log: `C:\ProgramData\HosMonitorServer\server-setup.log`
- Server data/config: `C:\ProgramData\HosMonitorServer`
- Agent setup log: `C:\ProgramData\HosMonitor\agent-setup.log`
- Agent log: `C:\ProgramData\HosMonitor\agent.log`
- Agent updater log: `C:\ProgramData\HosMonitor\agent-updates\updater.log`

รันทดสอบบนเครื่องพัฒนา:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

รายละเอียด third-party software อยู่ใน `THIRD_PARTY_NOTICES.md`
