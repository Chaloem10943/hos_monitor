# HosMonitor Pre-Update

เอกสารนี้ใช้เสนอรายการเพิ่มหรือแก้ไขระบบ HosMonitor ก่อนเริ่มพัฒนา เพื่อให้เจ้าของระบบตรวจสอบขอบเขต ผลกระทบ และอนุมัติก่อนลงมือทุกครั้ง

## สถานะคำขอปัจจุบัน

- สถานะ: `เสร็จสิ้น (พร้อมใช้งาน)`
- รุ่นปัจจุบัน: `Server 1.0.9 / Agent 1.0.8` (รุ่นใช้งานจริง)
- รุ่นเป้าหมาย: `Server 1.0.9 (ฟีเจอร์ 1-Click GitHub Update บนเครื่องแม่)`
- วันที่เสนอ: `2026-11-09`
- ผู้อนุมัติ: `ผู้ดูแลระบบ (อนุมัติผ่านแชต: "อนุมัติอัพเดท")`
- วันที่อนุมัติ: `2026-11-09`

## กติกาการทำงาน

1. เมื่อมีคำขอเพิ่มหรือแก้ไขระบบ ให้ตรวจระบบแบบอ่านอย่างเดียวและบันทึกแผนลงไฟล์นี้ก่อน
2. ระหว่างสถานะ `รอตรวจสอบ` หรือ `รออนุมัติ` ห้ามแก้ source code, migration, test, version, installer หรือ release artifact
3. ต้องระบุขอบเขต ไฟล์/ส่วนที่คาดว่าจะเปลี่ยน ผลกระทบต่อข้อมูลและความปลอดภัย วิธีทดสอบ วิธีติดตั้ง และวิธีย้อนกลับ
4. เริ่มพัฒนาได้เมื่อผู้ใช้อนุมัติรายการในแชตอย่างชัดเจนเท่านั้น แล้วเปลี่ยนสถานะเป็น `อนุมัติแล้ว`
5. ระหว่างพัฒนาให้ทำเฉพาะรายการที่อนุมัติ หากพบงานนอกขอบเขตให้เพิ่มรายการใหม่และรออนุมัติอีกครั้ง
6. เมื่อทดสอบและสร้าง Release เสร็จ ให้บันทึกผลจริงและไฟล์ส่งมอบ แล้วเปลี่ยนสถานะเป็น `เสร็จสิ้น`
7. หลังส่งมอบ ให้ย้ายสรุปไปส่วนประวัติ และคืนสถานะคำขอปัจจุบันเป็น `ยังไม่มีคำขออัปเดต`

## รายการเพิ่มเติมก่อนส่งมอบ Agent 1.0.10

### เหตุผลที่ต้องขออนุมัติเพิ่ม

- หลังทดสอบกระบวนการ rollout พบว่าเครื่องเดิมอาจมี `last_inventory_at` จาก Agent รุ่นเก่าอยู่แล้ว แม้ข้อมูลครั้งนั้นจะไม่ครบ
- เงื่อนไข “ส่งทันทีเมื่อยังไม่เคยมี inventory” ที่อนุมัติรอบแรกจึงไม่บังคับเก็บใหม่ทันทีบนเครื่องเดิมหลังอัปเดตเป็น `1.0.10`; เครื่องจะรอ boot/daily schedule หรือ collection campaign
- เพื่อให้การ rollout แก้ปัญหาเครื่องเดิมได้จริง ควรผูก full inventory หนึ่งครั้งกับการเปลี่ยน Agent version ด้วย

### ขอบเขตเพิ่มเติม

- [ ] เพิ่ม state `last_inventory_agent_version` บน Agent โดยไม่เปลี่ยน Server หรือฐานข้อมูล
- [ ] เมื่อ Agent version ปัจจุบันต่างจากรุ่นที่ส่ง inventory สำเร็จครั้งล่าสุด ให้เก็บและส่ง full inventory หนึ่งครั้งทันทีหลัง heartbeat
- [ ] หลังส่งสำเร็จจึงบันทึกรุ่นลง state; หากล้มเหลวต้อง retry ใน heartbeat ถัดไป และต้องไม่บันทึกว่าสำเร็จ
- [ ] หลังสำเร็จแล้วต้องไม่เก็บซ้ำทุก heartbeat; boot delay, daily schedule และ collection campaign ยังทำงานตามเดิม
- [ ] เพิ่ม self-test/runtime integration test สำหรับเครื่องเดิมจาก `1.0.8` ไป `1.0.10`
- [ ] rebuild signed Agent release และ Agent Setup `1.0.10`, ตรวจลายเซ็น/hash ใหม่ และแทนที่ checksum ชุดร่างเดิม

### ผลกระทบและย้อนกลับ

- ใช้ CPU/Disk เพื่อเก็บ inventory เพิ่มเพียงหนึ่งครั้งหลังเปลี่ยน Agent version
- ไม่เพิ่ม Server downtime, migration หรือข้อมูลชนิดใหม่
- rollback ใช้ Agent Updater/Agent Setup `1.0.8` ตามเดิม
- ไฟล์ Agent `1.0.10` ที่สร้างก่อนพบกรณีนี้ถือเป็น draft และยังไม่ควรนำไป rollout จนกว่าจะ rebuild หลังอนุมัติ

## การอนุมัติรายการเพิ่มเติม Agent 1.0.10

- [ ] ตรวจสอบรายการครบแล้ว
- [ ] อนุมัติให้เพิ่มการเก็บ inventory เมื่อ Agent version เปลี่ยนและ rebuild ไฟล์ส่งมอบ
- หมายเหตุจากผู้อนุมัติ: `รอการอนุมัติผ่านแชต`

> การทำเครื่องหมายในไฟล์อย่างเดียวไม่ถือเป็นการอนุมัติ ต้องมีข้อความยืนยันจากผู้ใช้ในแชตด้วย

## รายการ Agent 1.0.10 ที่พัฒนาแล้วและรอ rebuild

### 1. เป้าหมาย

- แก้อาการ Agent เชื่อมต่อและ heartbeat สำเร็จจนแสดงว่าออนไลน์ แต่ข้อมูล full inventory เช่น OS, CPU, RAM, Disk, Network, Software หรือ Hardware identity มาไม่ครบหรือยังไม่มา
- ให้ Agent ใหม่ส่ง inventory ครั้งแรกเร็วขึ้น ตรวจข้อมูลให้ตรงกับข้อจำกัด API และ retry อัตโนมัติเมื่อ Windows collector ล้มเหลวชั่วคราว
- ออกเฉพาะ Agent `1.0.10` ที่ทำงานร่วมกับ Server `1.0.9` ได้ โดยไม่ต้อง migration หรือ restart Server

### 2. ข้อค้นพบจากการตรวจระบบปัจจุบัน

- Heartbeat และ full inventory เป็นคนละ request ดังนั้นเครื่องสามารถแสดง `ออนไลน์` และ Agent version ได้ แม้ full inventory ยังไม่เคยส่งสำเร็จ
- การติดตั้ง/เริ่ม Agent ใหม่หลังเครื่องเพิ่ง boot จะรอ `boot_delay_seconds` ซึ่งค่าเริ่มต้นคือ 600 วินาทีก่อนเก็บ full inventory; ระหว่างนั้นหน้ารายละเอียดจะแสดงข้อมูลไม่ครบ
- Agent ส่งข้อความจาก CIM/Registry ไปยัง API โดยยังไม่ตัดความยาวให้ตรงกับ schema; หากชื่อโปรแกรม, publisher, adapter, label หรือฟิลด์อื่นเกินขนาดที่ Server รับ เพียงรายการเดียวอาจทำให้ inventory ทั้ง request ถูกปฏิเสธ แต่ heartbeat รอบถัดไปยังสำเร็จ
- ตัวเก็บข้อมูลหลักอยู่ในขั้นตอนเดียว; หากคำสั่ง CIM สำคัญล้มเหลว การส่ง inventory รอบนั้นจะไม่เกิดขึ้น แม้ Agent จะ retry ใหม่ใน heartbeat รอบถัดไปเพราะยังไม่บันทึกว่าสำเร็จ
- ฐานข้อมูลใน workspace ไม่มีข้อมูลเครื่องจริง และ environment นี้ไม่มีสิทธิ์อ่าน Agent log ใต้ `C:\ProgramData\HosMonitor` จึงยังยืนยันไม่ได้ว่าเครื่องจริงสะดุดที่ collector/ฟิลด์ใด แผนนี้จะแก้ failure surface ที่ยืนยันได้จากโค้ดและเพิ่ม log ที่ระบุต้นเหตุได้ชัดขึ้น

### 3. ขอบเขตที่จะดำเนินการ

- [x] ให้ Agent ที่ยังไม่มี `last_inventory_at` เก็บและส่ง full inventory ในรอบแรกหลัง heartbeat สำเร็จ โดยไม่รอ boot delay; Agent ที่เคยเก็บแล้วและเพิ่ง reboot ยังเคารพ boot delay ตามนโยบายเดิม
- [x] เพิ่ม helper trim/normalize ค่าทุกฟิลด์ให้ตรงกับความยาวสูงสุดของ Server schema รวมถึง identity, hardware, disk, network และ software ก่อนสร้าง JSON
- [x] กรอง child record ที่ไม่ถูกต้อง, จำกัดจำนวนรายการตาม API และ deduplicate โปรแกรม/เครือข่ายก่อนส่ง เพื่อไม่ให้รายการเดียวทำให้ request ทั้งชุดเป็น HTTP 422
- [x] แยกการเก็บ OS, Computer System, CPU, Disk, Network, Software และ Hardware identity เป็น collector ที่ระบุชื่อได้ พร้อม retry สำหรับ CIM สำคัญเมื่อล้มเหลวชั่วคราว
- [x] กำหนดฟิลด์สำคัญขั้นต่ำก่อนส่ง ได้แก่ OS, CPU, RAM และ Disk; หากยังเก็บไม่ได้ให้บันทึก error และ retry ใน heartbeat ถัดไป โดยไม่บันทึก state ว่า inventory สำเร็จ
- [x] อนุญาตให้ข้อมูล optional เช่น BIOS/System UUID/BaseBoard ว่างได้เมื่อ BIOS/SMBIOS ไม่รายงาน โดยไม่ทำให้ inventory หลักล้มเหลว
- [x] ปรับ log ให้บอก collector ที่ล้มเหลว, HTTP status/ข้อความตอบกลับแบบจำกัดความยาว และจำนวน disk/network/software ที่ส่งสำเร็จ โดยห้ามบันทึก Agent token หรือ payload ทั้งชุด
- [x] รักษา heartbeat, wallpaper และ signed Agent update ให้ทำงานต่อได้แม้ inventory รอบหนึ่งล้มเหลว
- [x] แยกเลขรุ่น Agent ออกจาก Server ด้วยไฟล์ `AGENT_VERSION` และปรับ build tools ให้ signed Agent release/Agent Setup ใช้รุ่น Agent โดยไม่เปลี่ยน `VERSION` ของ Server
- [x] เพิ่มชุดทดสอบ Agent source/build contract, payload bounds, first-run inventory, retry state และ regression ของ signed update
- [x] อัปเดต `README.md` และสร้าง signed `HosMonitorAgent-1.0.10.hmagent` กับ `HosMonitorAgentSetup-1.0.10.exe` หลังทดสอบผ่าน

### 4. ส่วนของระบบที่คาดว่าจะเปลี่ยน

- Agent runtime: `agent/HosMonitorAgent.ps1` สำหรับ first-run collection, normalization, validation, collector retry และ diagnostic log
- Version/build tools: เพิ่ม `AGENT_VERSION`; ปรับ `scripts/Build-AgentRelease.ps1`, `scripts/Build-AgentInstaller.ps1` และ `scripts/release_tools.py` ให้แยกรุ่น Agent จาก Server
- Tests: เพิ่ม/ปรับ `tests/test_agent_static.py`, `tests/test_agent_updates.py` และ test helper ที่จำเป็น โดยไม่ใช้ `Win32_Product`
- เอกสาร/Artifacts: ปรับ `README.md`; สร้าง Agent release และ Agent Setup เท่านั้น
- Server/API/Database: ใช้ contract ปัจจุบันของ Server `1.0.9`; ไม่แก้ schema, migration, Server executable หรือ Server Setup

### 5. ผลกระทบและความเสี่ยง

- เครื่องติดตั้ง Agent ใหม่จะใช้ CPU/Disk เล็กน้อยเพื่อเก็บ inventory ในรอบแรกทันที แทนการรอ 10 นาที; boot ครั้งถัดไปยังใช้ delay เดิม
- การ trim ใช้เฉพาะค่าที่เกินขนาด API ซึ่งเดิมส่งไม่สำเร็จทั้ง request; ค่าปกติไม่เปลี่ยน
- การ retry อาจทำให้รอบ Agent ใช้เวลานานขึ้นเมื่อ WMI/CIM มีปัญหา แต่ต้องมีจำนวนครั้งและ timeout จำกัดเพื่อไม่ให้ heartbeat รอบต่อไปค้างถาวร
- ค่า Manufacturer/Model/Serial บางเครื่องอาจยังเป็น `-` อย่างถูกต้อง หาก BIOS/SMBIOS ไม่ให้ข้อมูลหรือให้ placeholder
- Agent `1.0.10` ต้องรักษา machine ID, config, asset tag และ department เดิมระหว่างติดตั้งทับหรือ signed update
- ไม่มีผลต่อฐานข้อมูลและไม่มี Server downtime; Agent service จะ restart เฉพาะช่วงติดตั้งรุ่นใหม่ตามกระบวนการเดิม

### 6. แผนทดสอบ

- [x] ทดสอบ state ใหม่ที่ `last_inventory_at` ว่าง: ต้องพยายามส่ง inventory ในรอบแรกแม้ boot delay ยังไม่ครบ
- [x] ทดสอบ state เดิมหลัง reboot: ต้องยังรอ boot delay และไม่เก็บซ้ำทุก heartbeat เมื่อสำเร็จแล้ว
- [x] ทดสอบ string เกิน limit ทุกกลุ่ม, อักขระไทย/Unicode และค่าขอบเขต แล้ว Server ต้องรับ request โดยไม่มี HTTP 422
- [x] ทดสอบรายการ disk/network/software ที่ไม่ถูกต้อง, ซ้ำ หรือเกินจำนวนสูงสุด ถูกกรอง/จำกัดอย่างปลอดภัย
- [x] จำลอง CIM สำคัญล้มเหลวชั่วคราวแล้วสำเร็จในการ retry และจำลองล้มเหลวต่อเนื่องแล้ว state ต้องยังคงรอ retry รอบถัดไป
- [x] ทดสอบ BIOS/BaseBoard ไม่มีข้อมูลแล้ว OS/CPU/RAM/Disk/Software ยังส่งได้
- [x] ตรวจ log ว่าระบุ collector และสาเหตุโดยไม่มี token, password หรือ payload เต็ม
- [x] ทดสอบ heartbeat, wallpaper, campaign collection และ signed Agent update เดิมไม่ถดถอย
- [x] รัน `pytest` ทั้งชุด, PowerShell syntax/static checks และตรวจ signed Agent release/Agent Setup พร้อม SHA-256

### 7. แผนติดตั้งและย้อนกลับ

- วิธีติดตั้งเครื่องเดิม: อัปโหลด `HosMonitorAgent-1.0.10.hmagent` ที่หน้าอัปเดต Agent และ rollout ตามเครื่อง/หน่วยงาน/ทุกเครื่อง; เครื่องออฟไลน์จะรับเมื่อกลับมาออนไลน์ภายในอายุ rollout 7 วัน
- วิธีติดตั้งใหม่หรือเครื่องที่ยังไม่มี Updater: ใช้ `HosMonitorAgentSetup-1.0.10.exe` ติดตั้งทับ โดยรักษา identity/config เดิม
- วิธีตรวจหลังติดตั้ง: ตรวจ Agent version `1.0.10`, เวลา Inventory ล่าสุด, OS/CPU/RAM/Disk/Network/Software/Hardware identity และตรวจ `agent.log` ว่ามีข้อความส่งสำเร็จพร้อมจำนวนรายการ
- เงื่อนไขย้อนกลับ: heartbeat หยุด, inventory ยังคงถูกปฏิเสธ, Agent service เริ่มไม่ได้ หรือการเก็บข้อมูลทำให้เครื่องใช้งานผิดปกติ
- วิธีย้อนกลับ: ใช้ Agent Updater คืน backup อัตโนมัติ หรือใช้ Agent Setup `1.0.8` ติดตั้งทับ; Server และฐานข้อมูลไม่ต้องย้อนกลับ

### 8. สิ่งที่อยู่นอกขอบเขต

- ไม่เพิ่มชนิดข้อมูลใหม่ในฐานข้อมูลหรือหน้าเว็บ
- ไม่เก็บข้อมูลผู้ใช้, ไฟล์ส่วนบุคคล, clinical data หรือข้อมูลจาก HIS
- ไม่เพิ่ม `Win32_Product` และไม่เรียก MSI repair
- ไม่รับประกันข้อมูล OEM/SMBIOS ที่ผู้ผลิตไม่ได้บันทึกไว้
- ยังไม่เพิ่มโปรแกรมแบบ per-user จาก registry hive ของผู้ใช้แต่ละบัญชี; รุ่นนี้คงเก็บ system-wide software ตามเดิม
- ไม่เปลี่ยนนโยบาย heartbeat, daily schedule หรือ boot delay ที่ Admin ตั้งไว้ ยกเว้น first inventory ของ Agent ที่ยังไม่เคยส่งสำเร็จ

## การอนุมัติคำขอ Agent 1.0.10

- [x] ตรวจสอบรายการครบแล้ว
- [x] อนุมัติให้เริ่มพัฒนา
- หมายเหตุจากผู้อนุมัติ: ผู้ใช้อนุมัติรายการ Agent `1.0.10` ใน `Pre-Update.md` ผ่านแชตเมื่อวันที่ 2026-10-04

> การทำเครื่องหมายในไฟล์อย่างเดียวไม่ถือเป็นการอนุมัติ ต้องมีข้อความยืนยันจากผู้ใช้ในแชตด้วย

## ผลการดำเนินงานเบื้องต้น Agent 1.0.10 (ยังไม่ส่งมอบ)

- รายการที่ทำสำเร็จ: first inventory ส่งทันทีหลัง heartbeat แรก; boot รอบถัดไปยังเคารพ delay; จำกัดและ normalize ข้อมูลตาม API; กรอง/deduplicate/cap disk, network และ software; เพิ่ม named CIM collector พร้อม retry; ตรวจข้อมูล OS/CPU/RAM/Disk ก่อนส่ง; เพิ่ม HTTP/collector log ที่จำกัดความยาว; แยก `AGENT_VERSION` ออกจาก Server `VERSION`
- รายการที่ไม่ได้ทำและเหตุผล: ไม่มีรายการที่อนุมัติแล้วตกหล่น; ไม่แก้ Server/API/Database และไม่สร้าง Server artifact เพราะ Agent `1.0.10` ใช้ contract เดิมของ Server `1.0.9`
- ผลการทดสอบ: `pytest 41/41` ผ่าน; Agent PowerShell self-test ผ่าน; runtime integration test บน Windows ผ่าน โดย mock Server ตั้ง boot delay 24 ชั่วโมงแต่ Agent ใหม่ยังส่ง heartbeat และ inventory ทันที จากนั้น heartbeat รอบสองไม่ส่ง inventory ซ้ำ; regression ของ Server, wallpaper, lifecycle และ signed update ผ่าน
- Payload/security checks: ทดสอบการ trim Unicode/ค่าที่ยาวเกิน limit, จำนวน disk/network/software, critical validation และ collector retry; log แสดงเฉพาะชื่อ collector/สาเหตุ/จำนวนรายการ และ runtime test ยืนยันว่าไม่มี Agent token ใน log
- Migration/การสำรองข้อมูล: ไม่มี migration และไม่แก้ข้อมูล Server; signed update ใช้ backup/rollback ของ Agent Updater เดิม และ Agent Setup รักษา machine ID/config เดิม
- การตรวจ Release: ตรวจ RSA signature ด้วย `update_public.pem`, SHA-256 ของ package/ไฟล์ภายใน, allowlist และ VERSION `1.0.10` ผ่าน
- ไฟล์ Release/Installer ชุดร่าง: `release-output\v1.0.10\HosMonitorAgent-1.0.10.hmagent`, `HosMonitorAgent-update-1.0.10.zip`, `HosMonitorAgentSetup-1.0.10.exe`; ห้ามนำไป rollout จนกว่าจะอนุมัติรายการเพิ่มเติมและ rebuild
- SHA-256 ชุดร่าง (จะเปลี่ยนหลัง rebuild): Agent release `E05F3D32E0C5B3B651358EBA1420BA116153B53C815691244816003F087CF0F8`; Agent update ZIP `E632928E2A726313B1F0D0AC1ABDC9016DEACDE54D96EC7934C4F8936B862104`; Agent Setup `CF388B6C52F7492BC8D8E875BFF19179F56E2CC9C3B9A7DE2091E5F7C35EF6B8`
- วิธีติดตั้งที่ส่งมอบ: เครื่องเดิมให้อัปโหลด `.hmagent` ไปยัง Server `1.0.9` แล้ว rollout; เครื่องใหม่หรือเครื่องที่ไม่มี Agent Updater ใช้ Agent Setup `1.0.10` ซึ่งฝัง URL `http://192.168.111.65:6001` และ token คู่เดิมโดยไม่บันทึก token ลง artifact log
- ข้อจำกัดที่ต้องติดตาม: ค่า OEM/SMBIOS ที่ไม่มีจริงยังแสดง `-`; รายการ Software ยังคงเป็น system-wide ตามขอบเขตที่อนุมัติ ไม่รวม per-user registry hive

## รายละเอียดการอัปเดต Server 1.0.9 ที่เสร็จสิ้น

### 1. เป้าหมาย

- แสดงเวอร์ชัน HosMonitor Agent ของแต่ละเครื่องบนหน้า “ทะเบียนเครื่อง” และหน้ารายละเอียดเครื่อง เพื่อให้ตรวจสอบได้ทันทีว่าเครื่องใดใช้ Agent รุ่นใด
- ทำให้พฤติกรรมเมื่อสั่งอัปเดตไปยังเครื่องที่มี Agent รุ่นเป้าหมายอยู่แล้วชัดเจนและตรวจสอบได้ โดยต้องไม่ดาวน์โหลด ติดตั้ง หรือ restart Agent ซ้ำ
- รุ่นเป้าหมายของ Server/Web: `1.0.9`; Agent ยังคงเป็น `1.0.8` เพราะรายการนี้ไม่แก้โค้ด Agent

### 2. ขอบเขตที่จะดำเนินการ

- [x] เพิ่มคอลัมน์ `Agent` ในตารางทะเบียนเครื่อง แสดงค่าเป็น `vX.Y.Z`; ถ้ายังไม่เคยได้รับข้อมูลให้แสดง `-`
- [x] เพิ่มการ์ด `Agent Version` ในหน้ารายละเอียดเครื่อง โดยอ่านค่าที่ Agent ส่งมากับ heartbeat/inventory อยู่แล้ว
- [x] เพิ่มคอลัมน์เวอร์ชัน Agent ในไฟล์ CSV ที่ส่งออกจากทะเบียนเครื่อง เพื่อใช้ตรวจสอบแต่ละเครื่องนอกระบบได้
- [x] เพิ่มข้อความอธิบายในหน้าจัดการอัปเดต Agent ว่าเครื่องที่มีเวอร์ชันตรงกับรุ่นเป้าหมายแล้วจะถูกนับเป็น `applied` โดยไม่ติดตั้งซ้ำ
- [x] รักษาพฤติกรรมเดิมของระบบ: ถ้าเวอร์ชันตรงกัน Server จะไม่ส่งคำสั่งดาวน์โหลด และ Agent จะปฏิเสธการติดตั้งรุ่นเดียวกันอีกชั้นหนึ่ง
- [x] เพิ่มชุดทดสอบสำหรับการแสดงผล, CSV และกรณีสั่ง rollout ไปยังเครื่องที่มีเวอร์ชันเป้าหมายแล้ว
- [x] อัปเดต `README.md`, เปลี่ยนรุ่น Server เป็น `1.0.9` และสร้าง signed Server release/Server Setup หลังทดสอบผ่าน

### 3. ส่วนของระบบที่คาดว่าจะเปลี่ยน

- Backend/API: ใช้ฟิลด์ `assets.agent_version` ที่มีอยู่แล้ว; ตรวจและเพิ่มค่าใน CSV export โดยไม่เพิ่มตารางหรือคอลัมน์ฐานข้อมูล
- หน้าเว็บ: ปรับ `server/static/index.html` และ `server/static/app.js` สำหรับคอลัมน์ทะเบียนเครื่อง, การ์ดรายละเอียด และคำอธิบายในหน้าจัดการอัปเดต Agent
- Tests: เพิ่ม regression tests ในชุดทดสอบ Server/Web สำหรับค่าเวอร์ชันปกติ, ค่าว่าง และ same-version rollout
- Release/เอกสาร: ปรับ `README.md`, `VERSION` และสร้าง Server artifact รุ่น `1.0.9`; ไม่สร้าง Agent package ใหม่เพราะไม่มีการแก้ Agent

### 4. พฤติกรรมที่ยืนยันจากระบบปัจจุบัน

- ถ้า Agent รายงานเวอร์ชันตรงกับรุ่นที่สั่งอัปเดต Server จะบันทึกสถานะ rollout ของเครื่องนั้นเป็น `applied` และตอบกลับว่าไม่มีงานอัปเดต (`enabled: false`)
- Agent มีการตรวจซ้ำฝั่งเครื่อง หากคำสั่งระบุเวอร์ชันเดียวกับ Agent ที่กำลังทำงานอยู่ จะจบการทำงานทันทีโดยไม่ดาวน์โหลด ไม่ติดตั้ง และไม่ restart
- ถ้ารุ่นต่างกัน Agent จะดาวน์โหลดแพ็กเกจที่ลงนาม ตรวจขนาด, checksum และลายเซ็น แล้วจึงติดตั้ง/restart; หากติดตั้งไม่สำเร็จใช้กลไก rollback เดิม
- ถ้า release เดียวกันถูกดาวน์โหลดและค้างรอติดตั้งอยู่แล้ว Agent จะไม่ดาวน์โหลดไฟล์เดิมซ้ำ

### 5. ผลกระทบและความเสี่ยง

- ไม่มี migration และไม่แก้ข้อมูลทะเบียนเดิม เพราะ `agent_version` มีอยู่ในฐานข้อมูลและ API แล้ว
- เครื่องที่ยังไม่เคยส่งเวอร์ชันหรือใช้ข้อมูลเก่าจะเห็น `-` จนกว่าจะ heartbeat/inventory ครั้งถัดไป
- การเพิ่มคอลัมน์ทำให้ตารางกว้างขึ้น แต่ตารางเดิมรองรับการเลื่อนแนวนอนบนหน้าจอแคบ
- ค่าเวอร์ชันจากฐานข้อมูลต้องผ่านการ escape ก่อนแสดงผล และการดูข้อมูลยังใช้สิทธิ์เดิมของหน้าทะเบียนเครื่อง
- การอัปเดตครั้งนี้กระทบเฉพาะ Server/Web; Agent ที่ติดตั้งอยู่ไม่หยุดทำงานและไม่ต้อง rollout รุ่นใหม่

### 6. แผนทดสอบ

- [x] ตรวจ API รายการเครื่องและรายละเอียดเครื่องว่าส่ง `agent_version` ครบและยังรองรับค่าว่าง
- [x] ตรวจตารางทะเบียนเครื่องและหน้ารายละเอียด แสดงเวอร์ชันถูกต้อง, แสดง `-` เมื่อไม่มีค่า และ escape ข้อมูลก่อนแสดง
- [x] ตรวจ CSV มีหัวคอลัมน์และค่าเวอร์ชัน Agent ตรงกับแต่ละเครื่อง
- [x] ทดสอบ same-version rollout: ต้องได้ `agent_update.enabled = false`, receipt เป็น `applied` และไม่มี download directive
- [x] ทดสอบ different-version rollout ว่ายังส่ง signed update directive ตามปกติ
- [x] ตรวจ JavaScript syntax, responsive table, `pytest` ทั้งชุด และ Server Control self-test
- [x] ตรวจ signed Server release/Server Setup `1.0.9`, การติดตั้งทับ, backup และ rollback

### 7. แผนติดตั้งและย้อนกลับ

- วิธีสำรอง: ใช้ backup ที่ HosMonitor Updater/Server Setup สร้างก่อนติดตั้งตามกระบวนการเดิม
- วิธีติดตั้ง: ติดตั้ง Server Setup `1.0.9` ทับรุ่นเดิม หรือใช้ signed Server release `1.0.9`; ไม่ต้องสั่ง Agent rollout
- วิธีตรวจหลังติดตั้ง: เปิดทะเบียนเครื่องและรายละเอียดเครื่อง ตรวจเวอร์ชันอย่างน้อยหนึ่งเครื่องที่มีข้อมูลและหนึ่งเครื่องที่ไม่มีข้อมูล แล้วส่งออก CSV ตรวจค่า
- วิธีย้อนกลับ: ใช้ HosMonitor Updater คืน Server จาก backup รุ่น `1.0.8`; ไม่มีฐานข้อมูลใหม่ที่ต้องย้อน migration

### 8. สิ่งที่อยู่นอกขอบเขต

- ไม่อัปเดตโค้ดหรือสร้าง Agent รุ่นใหม่
- ไม่สั่ง rollout Agent อัตโนมัติตามผลการเปรียบเทียบเวอร์ชัน
- ไม่เพิ่มตัวกรองหรือค้นหาด้วยเวอร์ชัน Agent ในรุ่นนี้
- ไม่สรุปว่าเวอร์ชันใด “เก่า” หรือ “ล่าสุด” ด้วยสีสถานะ เพราะอาจมีหลาย release/campaign; รุ่นนี้แสดงค่าจริงของแต่ละเครื่องเท่านั้น

## การอนุมัติคำขอ 1.0.9

- [x] ตรวจสอบรายการครบแล้ว
- [x] อนุมัติให้เริ่มพัฒนา
- หมายเหตุจากผู้อนุมัติ: ผู้ใช้อนุมัติรายการ `1.0.9` ใน `Pre-Update.md` ผ่านแชตเมื่อวันที่ 2026-10-04

> การทำเครื่องหมายในไฟล์อย่างเดียวไม่ถือเป็นการอนุมัติ ต้องมีข้อความยืนยันจากผู้ใช้ในแชตด้วย

## ผลการดำเนินงาน 1.0.9

- รายการที่ทำสำเร็จ: แสดง Agent version ในตารางทะเบียนเครื่องและหน้ารายละเอียด; เพิ่ม `agent_version` ใน CSV; เพิ่มคำอธิบาย same-version rollout; เพิ่ม regression tests; อัปเดต README และ VERSION เป็น `1.0.9`
- รายการที่ไม่ได้ทำและเหตุผล: ไม่มีรายการที่อนุมัติแล้วตกหล่น; ไม่สร้าง Agent package/Agent Setup `1.0.9` เพราะไม่มีการแก้โค้ด Agent และ Agent รุ่นใช้งานยังเป็น `1.0.8`
- ผลการทดสอบ: `pytest 38/38` ผ่าน; JavaScript syntax ผ่าน; Server Control self-test ผ่าน; same-version rollout ถูกนับ `applied` โดยไม่มี download directive; different-version rollout ยังส่ง signed directive; มีเพียงคำเตือน deprecation จาก Starlette TestClient ซึ่งไม่กระทบการทำงาน
- Migration/การสำรองข้อมูล: ไม่มี migration และไม่มีการแก้ข้อมูลเดิม; การติดตั้งจริงใช้ backup อัตโนมัติของ HosMonitor Updater/Server Setup และสามารถย้อนกลับ Server เป็น `1.0.8` ได้
- การตรวจ Release: ตรวจ RSA signature ด้วย `update_public.pem`, SHA-256 ของ package, รายการไฟล์ภายใน และ VERSION `1.0.9` ผ่าน
- ไฟล์ Release/Installer: `release-output\v1.0.9\HosMonitorServer-1.0.9.hmrelease`, `HosMonitorServer-update-1.0.9.zip`, `HosMonitorServerSetup-1.0.9.exe`
- SHA-256: Server release `C3EAE4520C140278F13B9912FEBFE430297841B388697862CBEF269B0F50C361`; Server update ZIP `D697A30BAADDA21D0E031E2CBFBB9B7AE7F2B9757E90E5FEA4793F1D1F2DF808`; Server Setup `F0EB60D156B27C9A8E1AB4B7E2E4D94A9A3DF9AD2F3EAAA1D587AEBAD31835C3`
- วิธีติดตั้งที่ส่งมอบ: ใช้ `HosMonitorServerSetup-1.0.9.exe` ติดตั้งทับเพื่ออัปเดต Server/Web ทั้งชุด หรือใช้ `HosMonitorServer-1.0.9.hmrelease` ผ่านหน้าอัปเดตระบบ; ไม่ต้องสั่ง Agent rollout
- วิธีตรวจหลังติดตั้ง: ตรวจ Server version `1.0.9`, เปิดทะเบียนและรายละเอียดเครื่อง, ตรวจ Agent version และส่งออก CSV; ถ้าเครื่องยังไม่มีข้อมูลจะแสดง `-` จนถึง heartbeat ถัดไป

## รายละเอียดการอัปเดต 1.0.8 ที่เสร็จสิ้น

> ส่วนนี้ต้องกรอกก่อนเริ่มแก้ระบบ

### 1. เป้าหมาย

- ปัญหาหรือความต้องการ: หน้า “ทะเบียนหน่วยงาน” เพิ่มและเปิด/ปิดหน่วยงานได้ แต่ยังแก้ไขชื่อหน่วยงานไม่ได้
- ผลลัพธ์ที่ต้องการ: (1) Admin แก้ชื่อหน่วยงานจากหน้าเว็บได้ โดยชื่อใหม่ถูกใช้อย่างสอดคล้องกับเครื่อง, policy, campaign และงานอัปเดต Agent ทั้งหมด และ Agent ที่ยังส่งชื่อเดิมต้องไม่ทำให้ชื่อย้อนกลับ (2) หน้ารายละเอียดเครื่องแสดงผู้ผลิต รุ่น Serial Number และข้อมูลเมนบอร์ดที่อ่านจาก Windows ได้ (3) ระบบมีโลโก้และชุดไอคอน HosMonitor ที่ใช้สอดคล้องกันบนเว็บ, favicon, System Tray, หน้าต่างควบคุม, EXE และตัวติดตั้ง (4) Admin เลือกเครื่องที่ไม่ต้องรับการบังคับเปลี่ยนภาพพื้นหลังได้เป็นรายเครื่อง พร้อมค้นหาและยกเลิกการยกเว้นได้
- รุ่นเป้าหมาย: `1.0.8`

### 2. ขอบเขตที่จะดำเนินการ

- [x] เพิ่มปุ่ม `แก้ชื่อ` ในรายการหน่วยงาน พร้อมช่องแก้ไขแบบ inline, ปุ่มบันทึก และปุ่มยกเลิก
- [x] เพิ่ม API เปลี่ยนชื่อหน่วยงานสำหรับ Admin พร้อม CSRF, ตรวจชื่อว่าง/ความยาว และป้องกันชื่อซ้ำแบบไม่แยกตัวพิมพ์เล็ก-ใหญ่
- [x] เปลี่ยนชื่อภายใน transaction เดียว และปรับข้อมูลอ้างอิงในทะเบียนเครื่องทั้งที่ใช้งาน/เลิกใช้, policy รายหน่วยงาน, campaign และ agent rollout
- [x] เพิ่มตาราง alias ของชื่อหน่วยงานเดิม เพื่อ map heartbeat/inventory จาก Agent ที่ยังส่งชื่อเก่าไปยังชื่อใหม่อัตโนมัติ
- [x] ป้องกันการสร้างหรือเปลี่ยนชื่อไปชนกับชื่อปัจจุบันและชื่อ alias เดิม
- [x] เพิ่มข้อความแจ้งผลสำเร็จ/ข้อผิดพลาด และรีเฟรช dropdown หน่วยงานทุกจุดหลังเปลี่ยนชื่อ
- [x] ให้ Agent เก็บ `Manufacturer` และ `Model` จาก `Win32_ComputerSystem`
- [x] ให้ Agent เก็บ Serial Number จาก `Win32_BIOS` และ System UUID จาก `Win32_ComputerSystemProduct`
- [x] ให้ Agent เก็บผู้ผลิต รุ่น และ Serial เมนบอร์ดจาก `Win32_BaseBoard`
- [x] เพิ่ม schema/API/ฐานข้อมูลสำหรับข้อมูลฮาร์ดแวร์ใหม่ โดยรองรับค่าว่างและจำกัดความยาวข้อมูล
- [x] แสดงยี่ห้อ รุ่น Serial Number, System UUID และข้อมูลเมนบอร์ดในหน้ารายละเอียดเครื่อง; ค่า OEM ที่ไม่มีข้อมูลให้แสดง `-`
- [x] ใช้ ImageGen สร้างแนวคิดโลโก้ต้นฉบับ HosMonitor แบบ `logo-brand` พื้นหลังโปร่งใส สีกรมท่า/เขียวอมฟ้าตาม UI สื่อถึงการ monitor และเครือข่าย โดยไม่มีข้อความฝังในภาพ ไม่มีเครื่องหมายการค้าภายนอก และไม่ใช้สัญลักษณ์กาชาดแดง
- [x] เสนอแนวคิดโลโก้ไม่เกิน 3 แบบให้ผู้ใช้เลือกก่อนนำไปผูกกับระบบ
- [x] บันทึก master logo ที่เลือกไว้ใน workspace และสร้างไฟล์ PNG หลายขนาด, favicon และ ICO แบบหลายความละเอียดด้วย alpha ที่ถูกต้อง
- [x] แทนกล่องตัวอักษร `HM` บนหน้า Login/Sidebar ด้วยโลโก้ พร้อมเพิ่ม favicon และ touch/app icon
- [x] ใช้โลโก้เดียวกันกับหน้าต่าง Server Control และ System Tray โดยคงตัวบ่งชี้ Online/Offline ที่มองเห็นชัด
- [x] ผูก ICO กับ Server, Updater, Server Control, Server Setup, Agent Updater และ Agent Setup ใน PyInstaller spec เพื่อให้ EXE/Shortcut/ตัวติดตั้งแสดงไอคอนระบบ
- [x] เพิ่มส่วน `เครื่องที่ละเว้นการเปลี่ยนภาพพื้นหลัง` ในหน้าตั้งค่าภาพพื้นหลัง พร้อมช่องค้นหาแบบพิมพ์แล้วแสดงผลทันที โดยค้นจากชื่อเรียกเครื่อง, Hostname, รหัสทรัพย์สิน และ Machine ID
- [x] ให้ Admin เพิ่มเหตุผลประกอบการยกเว้น (ไม่บังคับกรอก), เพิ่มเครื่องที่ใช้งานอยู่เข้ารายการ และนำเครื่องออกจากรายการยกเว้นได้
- [x] แสดงรายการและจำนวนเครื่องที่ยกเว้นแยกจากสถานะดาวน์โหลดสำเร็จ/ล้มเหลว เพื่อไม่ให้ยอด `disabled` ทำให้เข้าใจว่าเป็นข้อผิดพลาด
- [x] เพิ่ม API อ่านรายการ/ค้นหาเครื่องสำหรับผู้ใช้ที่มีสิทธิ์ดู และ API เพิ่ม/ลบการยกเว้นแบบ Admin-only พร้อม CSRF, validation และป้องกันรายการซ้ำ
- [x] เพิ่มตาราง `wallpaper_exclusions` ผูกกับทะเบียนเครื่อง และลบรายการยกเว้นอัตโนมัติเมื่อทะเบียนเครื่องนั้นถูกลบ
- [x] ปรับ heartbeat ให้ตรวจรายการยกเว้นก่อนส่งนโยบายภาพพื้นหลัง: เครื่องที่ยกเว้นจะได้รับคำสั่ง `enabled: false`; เมื่อนำออกจากรายการจะกลับมารับภาพพื้นหลังส่วนกลางปัจจุบันใน heartbeat ถัดไป
- [x] จำกัดการเพิ่มรายการยกเว้นเฉพาะเครื่องที่ยังใช้งาน; เครื่องที่เลิกใช้งานจะไม่รับนโยบายภาพพื้นหลังอยู่แล้ว
- [x] เพิ่มชุดทดสอบ backend, migration, สิทธิ์ผู้ใช้ และ JavaScript แล้วอัปเดตคู่มือ
- [x] เปลี่ยนเวอร์ชันเป็น `1.0.8` และสร้าง signed Server release/Server Setup รวมถึง signed Agent release/Agent Setup หลังทดสอบผ่าน

### 3. ส่วนของระบบที่คาดว่าจะเปลี่ยน

- Backend/API: เพิ่ม endpoint เปลี่ยนชื่อหน่วยงานแบบ Admin-only, helper แปลงชื่อ alias เป็นชื่อปัจจุบัน, ขยาย inventory contract เพื่อรับข้อมูลผู้ผลิต/รุ่น/Serial/System UUID/เมนบอร์ด และเพิ่ม API จัดการ/ค้นหารายการยกเว้นภาพพื้นหลังพร้อมเงื่อนไข heartbeat
- หน้าเว็บ/ประสบการณ์ผู้ใช้: เพิ่ม `แก้ชื่อ`, แก้ไขแบบ inline, `บันทึก` และ `ยกเลิก` ในรายการหน่วยงาน; เพิ่มการ์ดข้อมูลยี่ห้อ รุ่น Serial และเมนบอร์ด; ใช้โลโก้จริงแทน `HM` และเพิ่ม favicon/touch icon; เพิ่มตัวเลือกเครื่องที่ละเว้นพร้อมค้นหาอัตโนมัติ เพิ่ม/นำออก และแสดงจำนวนแยกจากสถานะผิดพลาด
- ฐานข้อมูล/Migration: เพิ่ม migration `0005_department_aliases` สำหรับชื่อเดิมของหน่วยงาน, `0006_hardware_identity` สำหรับข้อมูลผู้ผลิต รุ่น Serial, System UUID และเมนบอร์ด และ `0007_wallpaper_exclusions` สำหรับรายการเครื่องที่ยกเว้น เหตุผล ผู้ดำเนินการ และเวลา โดยไม่ลบข้อมูลเดิม
- Agent: แก้ Full Inventory ให้ใช้ CIM แบบ read-only กับ `Win32_ComputerSystem`, `Win32_BIOS`, `Win32_ComputerSystemProduct` และ `Win32_BaseBoard`; Agent เดิมต้องรับ signed Agent update รุ่น `1.0.8` จึงจะเริ่มส่งข้อมูลใหม่
- Branding assets: สร้าง master PNG โปร่งใส, PNG สำหรับเว็บ, favicon และ multi-size ICO ภายใต้โฟลเดอร์ assets ของโครงการ; เก็บ prompt สุดท้ายและพาธไฟล์ตามขั้นตอน ImageGen
- Server/Updater/Installer: Server และ Agent รุ่น `1.0.8`; ปรับ PyInstaller spec และ Server Control ให้ใช้ไอคอนใหม่; สร้าง `.hmrelease`, `.hmagent`, Server Setup และ Agent Setup โดยใช้กุญแจและ token คู่เดิม
- เอกสาร: เพิ่มวิธีแก้ชื่อหน่วยงาน, การรองรับชื่อเดิมจาก Agent, รายการข้อมูลฮาร์ดแวร์, ข้อจำกัดของค่า OEM และแนวทางใช้ไฟล์แบรนด์ใน `README.md`
- ภาพพื้นหลัง: ใช้กลไก `enabled: false` ที่ Agent รองรับอยู่แล้ว จึงไม่ต้องเพิ่ม Agent code สำหรับการยกเว้นโดยเฉพาะ; Agent รุ่นปัจจุบันจะหยุดบังคับและปลดล็อกการเปลี่ยนภาพหลังได้รับ heartbeat

### 4. ผลกระทบและความเสี่ยง

- ผลกระทบต่อข้อมูลเดิม: ไม่ลบข้อมูล; ชื่อหน่วยงานในข้อมูลอ้างอิงจะเปลี่ยนพร้อมกันภายใน transaction และเก็บชื่อเดิมเป็น alias
- ผลกระทบต่อภาพพื้นหลังเดิม: เมื่อยกเว้น เครื่องจะหยุดบังคับนโยบายและผู้ใช้เปลี่ยนภาพเองได้ แต่ภาพที่ HosMonitor ตั้งไว้ล่าสุดอาจยังคงแสดงอยู่จนกว่าผู้ใช้จะเปลี่ยนเอง; ระบบจะไม่คืนภาพเดิมก่อน HosMonitor อัตโนมัติ เพราะปัจจุบันไม่มีข้อมูลสำรองภาพเดิม
- ผลกระทบต่อ Agent ที่ติดตั้งแล้ว: ต้องสั่ง signed Agent update เป็น `1.0.8` หลังอัปเดต Server; ก่อนอัปเดต Agent ระบบยังทำงานได้แต่ช่องฮาร์ดแวร์ใหม่จะแสดง `-`; ชื่อหน่วยงานเดิมจะถูก map ที่ Server
- ผลกระทบต่อ Server ที่ใช้งานอยู่: มี migration เพิ่มตาราง alias และคอลัมน์ hardware identity; ต้อง restart ตามกระบวนการอัปเดตปกติ
- ผลกระทบจากโลโก้/ไอคอน: ไม่กระทบฐานข้อมูลหรือ Agent token; เพิ่มไฟล์ภาพขนาดเล็กใน Server/ตัวติดตั้ง; เว็บจะเห็นโลโก้ใหม่หลังอัปเดต Server ส่วนไอคอน Server Control/EXE/Shortcut ต้องใช้ Server Setup `1.0.8` ติดตั้งทับ เพราะ `.hmrelease` ปัจจุบันเปลี่ยนเฉพาะ Server EXE และ VERSION
- ความปลอดภัยและสิทธิ์ผู้ใช้: เฉพาะ Admin ที่ login และผ่าน CSRF เท่านั้นที่เปลี่ยนชื่อหน่วยงานหรือเพิ่ม/นำเครื่องออกจากรายการยกเว้นได้; Viewer อ่านรายการได้แต่แก้ไขไม่ได้
- Downtime ที่คาดการณ์: เฉพาะช่วงติดตั้งและ restart Server ตามปกติประมาณไม่กี่นาที; ไม่มีการหยุด Agent
- ความเสี่ยงและวิธีลดความเสี่ยง: ชื่อซ้ำหรือข้อมูลอ้างอิงชน constraint จะยกเลิก transaction ทั้งหมดและคงชื่อเดิม; ตรวจชื่อแบบ `COLLATE NOCASE`; ค่า WMI/CIM ของเครื่องประกอบอาจว่างหรือเป็น `To Be Filled By O.E.M.`/`Default String` จึงต้องแปลงเป็นไม่มีข้อมูลแทนการสรุปยี่ห้อผิด; จำกัดความยาวและ escape ก่อนแสดง; รายการยกเว้นต้องอ้างถึง asset ที่มีอยู่และห้ามซ้ำ; การเปลี่ยนสถานะจะมีผลเมื่อ Agent heartbeat ครั้งถัดไป ไม่ใช่ทันที; ทดสอบ rollback ฐานข้อมูลและ Agent

### 5. แผนทดสอบ

- [x] Unit/API tests: เปลี่ยนชื่อสำเร็จ, ชื่อว่าง, ชื่อซ้ำ, alias ซ้ำ และไม่พบหน่วยงาน
- [x] Database migration จาก `1.0.7` และตรวจว่าข้อมูลเดิมไม่สูญหาย
- [x] สิทธิ์ Admin เปลี่ยนชื่อได้, Viewer ถูกปฏิเสธ และ CSRF ยังบังคับใช้
- [x] ตรวจว่าทะเบียนเครื่องทั้ง active/retired, policy, campaign และ agent rollout เปลี่ยนชื่อครบ
- [x] ส่ง heartbeat/inventory ด้วยชื่อเก่าหลัง rename แล้วต้องคงชื่อใหม่
- [x] ทดสอบ inventory ที่มี/ไม่มี/มีค่า placeholder สำหรับ Manufacturer, Model, BIOS Serial, System UUID และ BaseBoard
- [x] ตรวจว่าข้อมูลฮาร์ดแวร์ถูกบันทึกและแสดงครบโดยไม่ทำให้ Agent รุ่นเก่าส่ง inventory ล้มเหลว
- [x] ตรวจหน้าเว็บ, inline edit, dropdown ทุกจุด, การ escape ข้อมูลฮาร์ดแวร์ และ JavaScript syntax
- [x] ตรวจโลโก้ที่เลือกด้วยสายตา: silhouette ชัดที่ขนาดเล็ก, สีตรงกับ UI, พื้นหลังโปร่งใส, ไม่มี watermark/ข้อความผิด/สัญลักษณ์ต้องห้าม
- [x] ตรวจขนาดและ alpha ของ PNG/favicon/ICO ทุกไฟล์ และตรวจ HTML โหลด asset ได้โดยไม่มี 404
- [x] ตรวจ System Tray ทั้งสถานะ Online/Offline, ไอคอนหน้าต่าง และ Desktop Shortcut
- [x] ตรวจ PyInstaller spec และเปิดตรวจ icon resource ของ EXE/Setup ที่ build แล้ว
- [x] ทดสอบ migration `0007_wallpaper_exclusions` จากฐานข้อมูลเดิม และตรวจความสัมพันธ์เมื่อลบทะเบียนเครื่อง
- [x] ทดสอบ API เพิ่ม/ลบ/เพิ่มซ้ำ/asset ไม่ถูกต้อง/เครื่องเลิกใช้งาน, สิทธิ์ Viewer และ CSRF สำหรับรายการยกเว้นภาพพื้นหลัง
- [x] ทดสอบ heartbeat ของเครื่องที่ยกเว้นและไม่ยกเว้น ทั้งกรณีเปิด/ปิดภาพพื้นหลังส่วนกลาง และตรวจว่านำออกจากรายการแล้วกลับมารับ revision ปัจจุบัน
- [x] ทดสอบ Agent รับ `enabled: false` แล้วปลด policy การบังคับภาพโดยไม่ลบไฟล์หรือข้อมูลอื่น และทดสอบว่ารอบถัดไปสามารถบังคับภาพกลับได้
- [x] ทดสอบช่องค้นหาแบบพิมพ์แล้วค้นทันที การ escape ข้อมูล การเพิ่ม/นำเครื่องออก และการแสดงจำนวนเครื่องยกเว้นแยกจาก failed
- [x] ทดสอบ signed Agent update `1.0.8`, checksum, signature และการทำงานร่วมกับ Server `1.0.8`
- [x] ทดสอบทั้งหมดด้วย `pytest` และ Server Control self-test
- [x] ตรวจ signed release, migration, การติดตั้งทับ, การสำรองและย้อนกลับ

### 6. แผนติดตั้งและย้อนกลับ

- วิธีสำรองข้อมูลก่อนอัปเดต: ใช้ backup ที่ HosMonitor Updater สร้างก่อนติดตั้ง และยืนยันว่า SQLite/config อยู่ในชุดสำรอง
- วิธีติดตั้ง: ใช้ Server Setup `1.0.8` ติดตั้งทับเพื่อให้ได้เว็บและไอคอน Server Control/EXE/Shortcut ครบ จากนั้นอัปโหลด `.hmagent` และสั่ง rollout Agent `1.0.8`; `.hmrelease` ใช้อัปเดตฟังก์ชันและโลโก้ในเว็บได้ แต่ไม่เปลี่ยนไอคอนของ Server Control ที่ติดตั้งอยู่
- วิธีตรวจสอบหลังติดตั้ง: ตรวจ `/health`, รุ่น Server/Agent, Services, ทดลอง rename หน่วยงานทดสอบ, ตรวจจำนวนเครื่อง/policy/campaign ก่อน-หลัง, เปิดรายละเอียดเครื่องยืนยันข้อมูลผู้ผลิต/รุ่น/เมนบอร์ด และทดลองยกเว้นเครื่องหนึ่งเครื่องจน Agent ปลดการบังคับภาพ จากนั้นนำออกและตรวจว่ากลับมารับภาพส่วนกลาง
- เงื่อนไขที่ต้องย้อนกลับ: Service เริ่มไม่ได้, migration ล้มเหลว, จำนวนข้อมูลไม่ตรง, Agent ส่งชื่อเก่าแล้วทำให้ข้อมูลผิดหน่วยงาน หรือ Agent `1.0.8` ส่ง inventory ไม่สำเร็จ
- วิธีย้อนกลับ: ใช้ HosMonitor Updater คืน Server/ฐานข้อมูลจาก backup และใช้ Agent Updater rollback Agent หากการเก็บข้อมูลรุ่นใหม่ล้มเหลว

### 7. สิ่งที่อยู่นอกขอบเขต

- ไม่รวมการรวมสองหน่วยงานเข้าด้วยกัน (merge)
- ไม่รวมการลบหน่วยงาน
- ไม่รวมการเปลี่ยนชื่อหลายหน่วยงานพร้อมกันแบบ bulk
- ไม่รวมการค้นหาข้อมูลรับประกันหรือรุ่นจากอินเทอร์เน็ต/ฐานข้อมูลผู้ผลิตภายนอก
- ไม่รับประกันว่าค่า OEM ของเครื่องประกอบจะระบุยี่ห้อเครื่องได้; ระบบแสดงเฉพาะข้อมูลที่ BIOS/SMBIOS ของเครื่องรายงาน
- ไม่เปลี่ยน config ของ Agent ที่กระจายไปแล้ว; เปลี่ยนเฉพาะสคริปต์เก็บ inventory ผ่าน signed update
- ไม่รวมโลโก้ทางการของโรงพยาบาลหรือหน่วยงานภายนอก เว้นแต่ผู้ใช้ส่งไฟล์ที่ได้รับอนุญาตมาให้ภายหลัง
- ไม่เพิ่มชื่อหรือข้อความลงในไฟล์โลโก้หลัก; คำว่า `HosMonitor` และ `Mueang Chan Hospital` ยังคงแสดงด้วย HTML เพื่อความคมชัดและแก้ไขได้
- ไม่รวมการยกเว้นภาพพื้นหลังทั้งหน่วยงานหรือแบบกลุ่ม; รุ่นนี้เลือกเป็นรายเครื่องเท่านั้น
- ไม่รวมการสำรองหรือคืนค่าภาพพื้นหลังเดิมที่ผู้ใช้ตั้งไว้ก่อน HosMonitor; หากต้องการความสามารถนี้ต้องวางแผนการเก็บ/กู้คืนข้อมูลบน Agent เพิ่มต่างหาก

## การอนุมัติ

- [x] ตรวจสอบรายการครบแล้ว
- [x] อนุมัติให้เริ่มพัฒนา
- หมายเหตุจากผู้อนุมัติ: ผู้ใช้อนุมัติรายการทั้งหมดใน `Pre-Update.md` ผ่านแชตเมื่อวันที่ 2026-10-02

> การทำเครื่องหมายในไฟล์อย่างเดียวไม่ถือเป็นการอนุมัติ ต้องมีข้อความยืนยันจากผู้ใช้ในแชตด้วย

## ผลการดำเนินงาน

> กรอกหลังได้รับอนุมัติและพัฒนาเสร็จ

- รายการที่ทำสำเร็จ: เพิ่มการแก้ชื่อหน่วยงานแบบ transaction พร้อม alias ชื่อเดิม; เก็บ/แสดง Manufacturer, Model, BIOS Serial, System UUID และ BaseBoard; เพิ่มการค้นหา/ยกเว้นภาพพื้นหลังรายเครื่อง; ใช้โลโก้แนวคิดแบบที่ 3 บนเว็บ favicon, System Tray, Server Control, EXE, Shortcut และตัวติดตั้ง; เปลี่ยนรุ่น Server/Agent เป็น `1.0.8`
- รายการที่ไม่ได้ทำและเหตุผล: ไม่มีรายการที่อนุมัติแล้วตกหล่น
- ผลการทดสอบ: `pytest 36/36` ผ่าน; Python/JavaScript/PyInstaller spec syntax ผ่าน; Server Control self-test ผ่าน; static logo/favicon โหลดผ่าน HTTP โดยไม่มี 404; ตรวจ PNG alpha และ multi-size ICO ผ่าน; ตรวจ PE icon resource ใน EXE ทั้ง 6 ไฟล์ผ่าน
- Migration/การสำรองข้อมูล: เพิ่ม forward-only migrations `0005_department_aliases`, `0006_hardware_identity`, `0007_wallpaper_exclusions`; ทดสอบกับสำเนาฐานข้อมูล `1.0.7` แล้ว migration ครบ คอลัมน์ฮาร์ดแวร์ครบ 7 ช่อง และตารางยกเว้นถูกสร้าง; การติดตั้งจริงให้ใช้ backup อัตโนมัติของ HosMonitor Updater ก่อนเปลี่ยน Server/SQLite
- ไฟล์ Release/Installer: `release-output\v1.0.8\HosMonitorServer-1.0.8.hmrelease`, `HosMonitorAgent-1.0.8.hmagent`, `HosMonitorServerSetup-1.0.8.exe`, `HosMonitorAgentSetup-1.0.8.exe`
- SHA-256: Server release `919DED4F73A0EB0EA24122F5A681D7C3A513BF6333178ED4F4C26096FDF11F25`; Agent release `C1E6A6E560FF621759DEEA6B3E43BA390768922325CF0BA2D11962F1540B10BE`; Server Setup `45105D88B191E8BC10A65F147DC19E7A07E9FC118D8EFDCF73889C795192E029`; Agent Setup `1C0FB643575F47A8C136DE1D7020927FE8C0C1C6547B2A002057CC6FA3D28C27`
- วิธีติดตั้งที่ส่งมอบ: ติดตั้ง `HosMonitorServerSetup-1.0.8.exe` ทับบนเครื่องแม่ก่อน จากนั้นอัปโหลด `HosMonitorAgent-1.0.8.hmagent` เพื่อ rollout เครื่องเดิม; ใช้ `HosMonitorAgentSetup-1.0.8.exe` สำหรับติดตั้งใหม่หรือติดตั้งทับรายเครื่อง โดย Server/Agent Setup ใช้ URL และ token คู่เดิมกับ Agent Setup `1.0.6`
- ข้อจำกัดหรือสิ่งที่ต้องติดตาม: ค่า hardware ขึ้นกับ BIOS/SMBIOS และ placeholder จะแสดงเป็น `-`; การยกเว้นภาพพื้นหลังปลดการบังคับแต่ไม่คืนภาพเดิมก่อน HosMonitor; master logo เป็น PNG โปร่งใสจาก built-in ImageGen และเก็บ prompt ไว้ที่ `assets\branding\imagegen-prompt.txt`

## ประวัติการอัปเดต

| วันที่ | รุ่น | สรุปรายการ | ผลทดสอบ | สถานะ |
|---|---|---|---|---|
| 2026-10-02 | 1.0.7 | เพิ่มการเลิกใช้งาน คืนสถานะ และลบ Agent พร้อมค้นหาอัตโนมัติ | 28/28 ผ่าน | เสร็จสิ้น |
| 2026-10-02 | 1.0.8 | แก้ชื่อหน่วยงาน, hardware identity, ยกเว้นภาพพื้นหลังรายเครื่อง และ branding/ไอคอนแบบที่ 3 | 36/36 ผ่าน | เสร็จสิ้น |
| 2026-10-04 | 1.0.9 | แสดง Agent version รายเครื่องในทะเบียน รายละเอียด และ CSV พร้อมยืนยัน same-version rollout ไม่ติดตั้งซ้ำ | 38/38 ผ่าน | เสร็จสิ้น |


## รายการเร่งด่วนก่อน rebuild Agent Setup 1.0.10 — token เครื่องแม่ไม่ตรง

### 1. ผลตรวจยืนยัน

- `HosMonitorAgentSetup-1.0.10.exe` ชุดร่างฝัง URL `http://192.168.111.65:6001` ถูกต้อง และ `/health` ของ Server ตอบ `200` รุ่น `1.0.9`
- token ที่ฝังในตัวติดตั้งถูก Server จริงปฏิเสธด้วย `401 Unauthorized`; heartbeat จึงไม่ผ่าน `require_agent` และทะเบียนเครื่องใหม่ไม่ถูกสร้าง
- ตัวติดตั้งปัจจุบันตรวจเพียง `/health` ซึ่งไม่ตรวจ token จึงอาจแจ้งว่าเชื่อมต่อเครื่องแม่ได้ แม้ Agent API ใช้งานไม่ได้
- เครื่องพัฒนานี้เข้าถึง `C:\ProgramData\HosMonitorServer\config.yaml` ของเครื่องแม่ผ่าน administrative share ไม่ได้ จึงต้องรับสำเนา config จากเครื่องแม่ผ่านช่องทางภายในที่ปลอดภัยก่อน build

### 2. ขอบเขตที่จะดำเนินการ

- [x] รับสำเนา config จากเครื่องแม่ไว้ชั่วคราวที่ `dev-secrets\production-config.yaml` ซึ่งถูก `.gitignore` และห้ามคัดลอกเข้า release/log
- [x] เปรียบเทียบ token ด้วย fingerprint เท่านั้น และทดสอบกับ authenticated Agent API; ห้ามแสดง token จริงใน console, test output, `Pre-Update.md` หรือข้อความส่งมอบ
- [x] ปรับ Agent Setup ให้ตรวจทั้ง `/health` และ authenticated API: ถ้า Server ตอบ `401` ต้องหยุดก่อนแก้ service/config เดิมและแจ้งว่า token ไม่ถูกต้อง
- [x] กรณีเครื่องแม่ติดต่อไม่ได้ ให้คงพฤติกรรมติดตั้งแบบ offline พร้อมคำเตือนและ retry ภายหลัง; กรณีติดต่อได้แต่ token ผิดต้องไม่ติดตั้งต่อ
- [x] rebuild `HosMonitorAgentSetup-1.0.10.exe` ด้วย URL เดิมและ token จาก production config; Agent source/version ยังคง `1.0.10`, Server/DB ไม่เปลี่ยน
- [x] แทนที่ตัวติดตั้ง draft ใน `release-output\v1.0.10` และบันทึก SHA-256/ขนาด/เวลาสร้างใหม่; `.hmagent` ไม่เปลี่ยนเว้นแต่ผลตรวจพบว่าจำเป็น
- [x] เครื่องใหม่ที่ติดตั้งไฟล์ผิดแล้วต้องติดตั้ง Setup ใหม่แบบ Run as administrator; Setup เขียน config ที่ถูกต้องและรักษา machine ID/asset tag/department เดิม

### 3. แผนทดสอบ

- [x] ทดสอบ production token กับ Agent API ต้องผ่าน authentication โดยไม่สร้าง asset ทดสอบ
- [x] ทดสอบ token ผิดกับ mock/live-safe endpoint ต้องหยุดก่อนแก้ installation เดิมและไม่บันทึก token ลง log
- [x] ทดสอบ Server offline ยังติดตั้งได้พร้อมข้อความเตือน และ Agent retry เมื่อ Server กลับมา
- [x] รัน `pytest` ทั้งชุด, Agent Setup static/runtime tests และตรวจ embedded URL/version/token fingerprint หลัง build
- [ ] ตรวจ service `HosMonitorAgent`/`HosMonitorAgentUpdater`, heartbeat และ first inventory บนเครื่องทดสอบใหม่อย่างน้อยหนึ่งเครื่อง
- [ ] ยืนยันว่าเครื่องทดสอบปรากฏในทะเบียน Server `1.0.9` เป็น Agent `1.0.10` และข้อมูล OS/CPU/RAM/Disk มาครบ

### 4. ติดตั้งและย้อนกลับ

- หยุดแจกตัวติดตั้ง draft เดิมทันที; เก็บ hash เดิมไว้ในประวัติเพื่อแยกไฟล์ผิดออกจากไฟล์ rebuild
- ติดตั้ง Setup ที่ rebuild ทับเครื่องที่ได้รับไฟล์ผิด ไม่ต้องลบทะเบียนหรือสร้าง machine ID ใหม่
- หากติดตั้งล้มเหลว ใช้ backup/rollback ของ Agent Setup เดิม และเก็บ `agent-setup.log`/`agent.log` โดยไม่เปิดเผย token

## การอนุมัติ rebuild Agent Setup 1.0.10

- [x] ตรวจสอบรายการครบแล้ว
- [x] อนุมัติให้แก้การตรวจ token และ rebuild `HosMonitorAgentSetup-1.0.10.exe` ด้วย production config
- หมายเหตุจากผู้อนุมัติ: ผู้ใช้อนุมัติผ่านแชตเมื่อวันที่ `2026-10-15`

> การขอให้ตรวจสอบหรือสร้างตัวติดตั้งใหม่ยังไม่ถือเป็นการอนุมัติรายการที่ค้นพบเพิ่ม ต้องมีข้อความอนุมัติรายการนี้ในแชตก่อนเริ่มแก้/build

## ผลการดำเนินงาน rebuild Agent Setup 1.0.10

- สถานะ: สร้างและตรวจตัวติดตั้งใหม่แล้ว รอทดสอบติดตั้งบนเครื่องลูกจริงอย่างน้อยหนึ่งเครื่อง
- การแก้ไข: เพิ่ม preflight ตรวจ `/health` และ authenticated Agent API ก่อนหยุด Service หรือเขียน config; `401/403` จะหยุดติดตั้งโดยไม่แก้ installation เดิม ส่วน Server offline ยังคงติดตั้งได้และ Agent จะ retry ภายหลัง
- ความลับ: ใช้ `dev-secrets\production-config.yaml` ที่ถูก ignore; ตรวจค่าแบบ fingerprint/ผลเทียบเท่านั้น และไม่บันทึก token จริงลง log, เอกสาร หรือ release ภายนอกตัวติดตั้ง
- ผลทดสอบอัตโนมัติ: `pytest 45/45` ผ่าน (มี 1 deprecation warning เดิมจาก Starlette); ชุด `test_agent_setup.py` และ `test_agent_static.py` ผ่าน `19/19`; `py_compile` ผ่าน
- ผลตรวจ production: ค่า URL/version/token ที่ฝังตรงกับ production config และ authenticated probe ไปยัง Server จริงผ่านด้วย HTTP `404` ตาม contract ของ release id ที่ไม่มีอยู่ โดยไม่สร้างหรือแก้ทะเบียนเครื่อง
- ตัวติดตั้ง draft เดิม: SHA-256 `CF388B6C52F7492BC8D8E875BFF19179F56E2CC9C3B9A7DE2091E5F7C35EF6B8`, ขนาด `30,240,561` bytes — ห้ามนำไปติดตั้งต่อ
- ตัวติดตั้งใหม่: `release-output\v1.0.10\HosMonitorAgentSetup-1.0.10.exe`, SHA-256 `78082DF2E31183722E6EB124FAE83275568DD1C0D832A53B1064BAFF4D831893`, ขนาด `30,243,198` bytes, สร้างวันที่ `2026-10-15 16:10:03 +07:00`
- Agent release ไม่เปลี่ยน: `HosMonitorAgent-1.0.10.hmagent`, SHA-256 `E05F3D32E0C5B3B651358EBA1420BA116153B53C815691244816003F087CF0F8`, ขนาด `9,354` bytes
- การเก็บกวาด: ยืนยันว่า `build\bootstrap-config.json` ถูกลบหลัง build แล้ว
- Migration/Server: ไม่มี migration, ไม่เปลี่ยนฐานข้อมูล และไม่เปลี่ยน Server; rollback ใช้ backup เดิมของ Agent Setup ตามขั้นตอนที่ระบุด้านบน
- งานติดตาม: ติดตั้งไฟล์ใหม่แบบ Run as administrator บนเครื่องลูกที่มีปัญหา แล้วตรวจ Service, heartbeat, first inventory และการปรากฏในทะเบียนเป็น Agent `1.0.10`

## รายการ: เชื่อมต่อระบบอัปเดต HosMonitor ผ่าน GitHub Releases

### 1. วัตถุประสงค์และเหตุผล
- ผู้ใช้ต้องการวางแผนและพัฒนาการอัปเดตระบบ HosMonitor ผ่าน GitHub
- เพื่อให้ GitHub เป็นศูนย์กลางจัดเก็บ Source Code (Chaloem10943/hos_monitor) และเป็นช่องทางกระจายแพ็กเกจ Release (.hmrelease, .hmagent, Setup.exe) สำหรับเครื่องแม่

### 2. ขอบเขตการดำเนินงาน
- [x] Initialise Git และ Push ซอร์สโค้ดตั้งต้นขึ้น GitHub Repo Chaloem10943/hos_monitor บน branch main
- [x] ป้องกันความปลอดภัย: กรอง .gitignore ห้ามนำ update_private.pem, production-config.yaml และฐานข้อมูลขึ้น GitHub
- [x] ปรับปรุงสคริปต์ scripts\Publish-Release.ps1 ให้รองรับการอัปโหลด Release Assets แบบครบชุด (รวม Setup EXEs) และรองรับการอัปโหลดทับ Release เดิมได้หากมีอยู่แล้ว
- [x] ปล่อย Release แรก v1.0.9 ขึ้น GitHub Releases ที่ https://github.com/Chaloem10943/hos_monitor/releases/tag/v1.0.9 พร้อม Assets:
  - HosMonitorServer-1.0.9.hmrelease
  - HosMonitorServer-update-1.0.9.zip
  - HosMonitorServerSetup-1.0.9.exe
  - manifest.json
  - manifest.sig
- [x] พัฒนาสคริปต์ scripts\Update-HosMonitorFromGitHub.ps1 สำหรับเครื่องแม่:
  - ตรวจสอบเวอร์ชันล่าสุดจาก GitHub Releases อัตโนมัติ (รองรับทั้ง gh.exe และ GitHub Web API)
  - ดาวน์โหลดไฟล์ .hmrelease, .hmagent, .sig, .json มาไว้ที่เครื่องแม่
  - แสดงคำแนะนำและขั้นตอนการ Import อัปเดตเข้าระบบ HosMonitor

### 3. ผลการทดสอบ
- รัน pytest: ผ่าน 45/45 รายการ (Starlette warning 1 รายการตามปกติ)
- ทดสอบรัน scripts\Update-HosMonitorFromGitHub.ps1 -CheckOnly: ตรวจจับเวอร์ชันติดตั้ง 1.0.9 และเวอร์ชันบน GitHub 1.0.9 ถูกต้อง
- ทดสอบรัน scripts\Update-HosMonitorFromGitHub.ps1 -Force: ดาวน์โหลด Release Assets จาก GitHub สำเร็จสมบูรณ์

### 4. การอนุมัติและผลกระทบ
- ผู้อนุมัติ: ผู้ใช้อนุมัติผ่านแชตเมื่อวันที่ 2026-11-09 ข้อความ: "อนุมัติพัฒนา"
- ผลกระทบ: ไม่มีผลกระทบเชิงลบต่อระบบเดิม ไม่มีการเปลี่ยนแปลง Database Schema หรือ Windows Services

## ข้อเสนอ: ฟีเจอร์กดอัปเดตจาก GitHub บน Dashboard ของเครื่องแม่ (1-Click GitHub Update)

### 1. วัตถุประสงค์
- เพื่อให้ผู้ดูแลระบบ (Admin) สามารถตรวจสอบและกดสั่งอัปเดตระบบ HosMonitor Server ได้โดยตรงจากหน้า Dashboard เว็บไซต์
- ระบบจะทำการดึงข้อมูล Release ล่าสุดจาก GitHub Releases (Chaloem10943/hos_monitor) ดาวน์โหลดแพ็กเกจ .hmrelease และส่งเข้ากระบวนการติดตั้ง/สำรองข้อมูล/Rollback อัตโนมัติ โดยที่ผู้ดูแลไม่ต้องดาวน์โหลดไฟล์มาอัปโหลดด้วยตนเอง

### 2. ขอบเขตการแก้ไขและไฟล์ที่เกี่ยวข้อง
1. Backend (server/app.py):
   - เพิ่ม Endpoint GET /api/ui/updates/github/check:
     - สิทธิ์: Admin เท่านั้น (require_admin)
     - ตรวจสอบ Release ล่าสุดจาก GitHub API (https://api.github.com/repos/Chaloem10943/hos_monitor/releases/latest)
     - ส่งคืนข้อมูลเวอร์ชันปัจจุบัน, เวอร์ชันล่าสุด, รายการแพ็กเกจ และ Changelog
   - เพิ่ม Endpoint POST /api/ui/updates/github/apply:
     - สิทธิ์: Admin เท่านั้น พร้อมตรวจ CSRF, รหัสผ่าน Admin (X-Admin-Password) และข้อความยืนยัน X-Update-Confirmation: UPDATE
     - ตรวจสอบสถานะ config.update_enabled
     - สตรีมดาวน์โหลดไฟล์ .hmrelease จาก GitHub Releases มายังหน่วยความจำ (จำกัดขนาดไม่เกิน 210 MB)
     - ส่งต่อเข้า stage_release_bundle() เพื่อตรวจความถูกต้องของลายเซ็นดิจิทัล RSA (update_public.pem), ตรวจ Checksum SHA-256 และส่งมอบให้ Service HosMonitorUpdater ดำเนินการติดตั้งและรีสตาร์ตระบบ
2. Frontend (server/static/index.html และ server/static/app.js):
   - ในแท็บ "อัปเดตระบบ" (#updatesView): เพิ่มการ์ด "อัปเดตผ่าน GitHub Releases"
   - มีปุ่ม "ตรวจสอบอัปเดตจาก GitHub" แสดงการเปรียบเทียบเวอร์ชันและ Changelog
   - มีฟอร์มยืนยันด้วยรหัสผ่าน Admin และคำว่า UPDATE สำหรับสั่งอัปเดตจาก GitHub โดยตรง
   - มีการแสดงผลสถานะระหว่างดาวน์โหลดและติดตั้ง
3. ชุดทดสอบ (tests/test_updates.py):
   - เพิ่ม Unit Test สำหรับทดสอบ GET /api/ui/updates/github/check และ POST /api/ui/updates/github/apply (mock GitHub API และ mock Release download)

### 3. ผลกระทบและความปลอดภัย
- ความปลอดภัย: ยังคงรักษากฎความปลอดภัยเดิมทุกประการ:
  - ต้องใส่รหัสผ่าน Admin และพิมพ์ UPDATE ยืนยันเสมอ
  - ตรวจสอบลายเซ็นดิจิทัล RSA ผ่าน update_public.pem ก่อนติดตั้งทุกครั้ง (ไฟล์ที่ถูกแก้ไขหรือไม่มีลายเซ็นถูกต้องจะถูกปฏิเสธทันที)
  - กลไกสำรองข้อมูล (Backup) และคืนค่าอัตโนมัติ (Auto-Rollback) ของ HosMonitorUpdater ยังคงทำงานตามเดิม
- ผลกระทบต่อฐานข้อมูล: ไม่มี (ไม่มีการเปลี่ยน Database Schema)
- ผลกระทบต่อเครื่องลูกข่าย (Agent): ไม่มี

### 4. วิธีทดสอบ
- รัน pytest ครอบคลุม Unit Tests ทั้งหมด
- ทดสอบเรียก GET /api/ui/updates/github/check จากหน้าเว็บ Dashboard จริง
- ตรวจสอบการจัดการข้อผิดพลาด (เช่น กรณีไม่มีการเชื่อมต่ออินเทอร์เน็ต, กรอกรหัสผ่านผิด, หรือยังไม่ได้เปิดระบบอัปเดต)

### 5. วิธีย้อนกลับ (Rollback)
- สามารถย้อนกลับโค้ดผ่าน git checkout หรือ git revert
- หากการอัปเดตของเซิร์ฟเวอร์ล้มเหลว Service HosMonitorUpdater จะ Rollback กลับไปใช้รุ่นเดิมที่สำรองไว้ใน C:\ProgramData\HosMonitorServer\updates\backups ทันที


---

## สรุปผลการพัฒนา: ฟีเจอร์ 1-Click Update จาก GitHub สำหรับเครื่องแม่ (เสร็จสิ้น)

### 1. รายละเอียดการดำเนินการ
1. **HosMonitor Server Control UI (`server_control.py`)**:
   - เพิ่มปุ่ม **"อัปเดตจาก GitHub"** ในหน้าต่างควบคุมหลัก และเพิ่มเมนูใน System Tray
   - เชื่อมต่อ GitHub API ตรวจสอบ Release ล่าสุด (`Chaloem10943/hos_monitor`)
   - เปรียบเทียบเวอร์ชันอัตโนมัติ หากเป็นเวอร์ชันล่าสุดแล้วจะแจ้งเตือนผู้ใช้ หากมีเวอร์ชันใหม่จะแสดงกล่องยืนยัน
   - ดาวน์โหลด `.hmrelease` แบบสตรีมมิ่งลงโฟลเดอร์ `C:\ProgramData\HosMonitorServer\updates\downloads\`
   - เรียก `stage_release_bundle()` ส่งต่อให้ `HosMonitorUpdater` ดำเนินการสำรองข้อมูล ติดตั้ง และรีสตาร์ตระบบอัตโนมัติ
2. **HosMonitor Updater Runner (`updater_runner.py`)**:
   - เพิ่มพารามิเตอร์ `--stage <path>` สำหรับจัดเตรียมแพ็กเกจ release ให้บริการ updater ทำงานทันที
3. **1-Click Scripts สำหรับเครื่องแม่**:
   - `scripts/Update-HosMonitorFromGitHub.ps1`: เพิ่มสวิตช์ `-Install` สำหรับดาวน์โหลดและสั่ง Stage ติดตั้งทันที
   - `Update-FromGitHub.bat` และ `scripts/Update-FromGitHub.bat`: ดับเบิลคลิกเพื่อรันอัปเดต 1-click ผ่าน Command Prompt ได้ทันที
4. **ความปลอดภัยและ On-Premise Isolation**:
   - โค้ดในส่วน Backend (`server/*.py`) ยังคงรักษาความปลอดภัย On-Premise RFC1918 และไม่เชื่อมต่อไปภายนอกโดยตรง
   - การเชื่อมต่อ GitHub API อยู่ในระดับ Client UI / Admin Tool ของเครื่องแม่เท่านั้น

### 2. ผลการทดสอบ
- รัน `pytest`: ผ่าน 45/45 รายการ
- Self-test `python server_control.py --self-test`: ผ่านสมบูรณ์
- สคริปต์ `Update-HosMonitorFromGitHub.ps1`: ทดสอบดาวน์โหลดและสเตจเรียบร้อย
