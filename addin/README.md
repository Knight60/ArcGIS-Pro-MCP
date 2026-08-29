# ArcGIS Pro MCP — C# add-in (hybrid)

Add-in ที่รันในโปรเซสของ ArcGIS Pro เอง ทำหน้าที่เป็น bridge หลักแทนฝั่ง Python
เพื่อกำจัด latency ที่เกิดจากข้อจำกัดของ thread

## ทำไมต้องมี

จากการทดสอบบน ArcGIS Pro 3.5.2:

| Thread | หน้าที่ | pump message |
|---|---|---|
| UI thread | หน้าต่าง Pro | ตลอดเวลา |
| Python thread | `arcpy.mp.ArcGISProject("CURRENT")` ใช้ได้**ที่นี่ที่เดียว** | ~ทุก 28 วินาทีตอน Pro ว่าง |

ฝั่ง Python จึงมี latency สูงเมื่อ Pro ไม่ได้ถูกใช้งาน แก้ไม่ได้ด้วยวิธีใด ๆ
ในฝั่ง Python เอง (ลองมาแล้วทั้ง `PumpWaitingMessages` loop, `GetMessage` loop
และ message-only window + timer)

add-in ไม่มีปัญหานี้เพราะใช้ `QueuedTask.Run` ส่งงานเข้า **Main CIM Thread**
ซึ่ง Pro ให้บริการต่อเนื่องอยู่แล้ว

## วิธีติดตั้งที่สั้นที่สุด (MCP over HTTP)

add-in พูด MCP ได้เองผ่าน HTTP **ไม่ต้องมีโปรเซส Python เลย**

```powershell
claude mcp add --transport http arcgis http://127.0.0.1:6520/mcp
```

เท่านี้จบ — ดับเบิลคลิก `.esriAddinX` ครั้งเดียว + คำสั่งข้างบนอีกครั้งเดียว

ทำได้เพราะ transport ต่างกัน:

| Transport | client ทำอะไร | ใช้กับ add-in ได้ไหม |
|---|---|---|
| stdio | **spawn โปรเซส** ใหม่แล้วคุยผ่าน stdin/stdout | ❌ add-in อยู่ในโปรเซส Pro ที่รันอยู่แล้ว |
| HTTP | ต่อไปที่ **URL** | ✅ add-in เปิด endpoint เองได้ |

tool schema ทั้ง 112 ตัวมาจาก [catalog.py](../src/arcgis_pro_mcp/catalog.py) ไฟล์เดียวกับที่ฝั่ง
Python ใช้ — export ด้วย `scripts/export_tool_schemas.py` แล้วฝังเป็น embedded
resource จึงไม่มีนิยาม tool ซ้ำสองที่

endpoint bind เฉพาะ `127.0.0.1` เพราะมันเปิดโปรเจกต์ที่ผู้ใช้เปิดอยู่ให้เข้าถึงได้

### ยังใช้ทาง Python ได้เหมือนเดิม

`arcgis-pro-mcp` (stdio) ยังคุยกับ add-in ผ่าน TCP 6510 ได้ตามปกติ ทั้งสองทาง
เปิดพร้อมกันได้

## สถาปัตยกรรม

```
AI client ──MCP over HTTP :6520/mcp ─┐
                                     │
AI client ──MCP stdio──► arcgis-pro-mcp ──TCP :6510──┐
                                     │               │
                                     ▼               ▼
              ┌─ C# Add-in (ในโปรเซส ArcGIS Pro) ─────────┐
              │   → QueuedTask.Run (Main CIM Thread)      │
              │   คำสั่งที่ไม่รู้จัก ─┐                    │
              └──────────────────────┼───────────────────┘
                                     ▼ :6511
                        Python bridge (execute_arcpy_code)
```

**protocol เหมือนเดิมทุกอย่าง** — newline-delimited JSON เดิม ฝั่ง MCP server,
tool catalog, tests และ CLI ใช้ต่อได้โดยไม่ต้องแก้

คำสั่งที่ add-in ยังไม่ได้ทำ จะถูกส่งต่อไป Python bridge อัตโนมัติ ทำให้
`execute_arcpy_code` และ handler อีก ~80 ตัวยังใช้ได้ระหว่างที่ทยอยย้าย

## ต้องมีอะไรบ้าง

| | ตอนพัฒนา | ตอนใช้งาน |
|---|---|---|
| ArcGIS Pro | ✅ | ✅ |
| .NET 8 SDK | ✅ | ❌ |
| Visual Studio | ไม่บังคับ (ใช้ `dotnet build` ได้) | ❌ |
| ArcGIS Pro SDK for .NET | เฉพาะเพื่อแพ็ก `.esriAddinX` | ❌ |

ผู้ใช้ปลายทางแค่ดับเบิลคลิกไฟล์ `.esriAddinX` ครั้งเดียว

## เวอร์ชันของ ArcGIS Pro

**ต้อง build แยกต่อ .NET generation ของ Pro** — ไม่ใช่เพราะ API เปลี่ยน แต่เพราะ
assembly ของ Pro ถูก build ด้วย framework ไหน โปรเจกต์นี้ก็ต้อง target ตัวนั้น
(C# ไม่ยอมให้อ้าง assembly ที่มาจาก framework ใหม่กว่า)

| ArcGIS Pro | `TargetFramework` | `desktopVersion` |
|---|---|---|
| 3.3 - 3.6 | `net8.0-windows` | `3.3` |
| **3.7+** | **`net10.0-windows`** | `3.7` |

ดูว่า Pro เวอร์ชันที่ลงไว้ target อะไรได้จาก `bin/ArcGISPro.runtimeconfig.json`
ในโฟลเดอร์ที่ติดตั้ง (ช่อง `"tfm"`)

build ให้เวอร์ชันเก่าโดยไม่แก้ไฟล์:

```powershell
dotnet build addin\ArcGISProMCP\ArcGISProMCP.csproj -p:TargetFramework=net8.0-windows
```

(ต้อง build บนเครื่องที่ลง Pro รุ่นนั้น เพราะ csproj อ้าง assembly จากที่ติดตั้งจริง)

### ตอนอัปเกรด Pro ต้องทำอะไรบ้าง

จากที่ทำจริงตอนอัปจาก 3.5.2 (net8.0) เป็น 3.7.1 (net10.0):

1. แก้ `TargetFramework` ให้ตรง แล้ว build - **โค้ดคำสั่งทั้ง 90 ตัวไม่ต้องแก้เลย
   สักบรรทัด** error ที่เจอเป็นเรื่อง framework ล้วน ๆ ไม่มี API ไหนหายไป
2. **regenerate `gp-parameters.json`** ด้วย arcpy ของเวอร์ชันใหม่:

   ```powershell
   "C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" `
       scripts\dump_gp_parameters.py
   ```

   ข้อนี้ห้ามข้าม: ถ้า tool ไหนแทรก parameter ใหม่กลางลำดับ ค่าจะไปลงผิดช่อง
   **โดยไม่มี error** ตารางเก่ายังดูใช้ได้อยู่
3. build อีกรอบ, restart Pro (`scripts/restart_pro.ps1`), ทดสอบ

`tools.json` มาจาก `catalog.py` ไม่ผูกกับเวอร์ชัน Pro

## Build

```powershell
dotnet build addin\ArcGISProMCP\ArcGISProMCP.csproj -c Release
```

`Esri.ProApp.SDK.Desktop.targets` (ติดตั้งมากับ Pro ที่
`...\ArcGIS\Pro\bin\`) จะ:

1. แพ็กเป็น `ArcGISProMCP.esriAddinX`
2. เรียก `RegisterAddIn.exe` ติดตั้งให้อัตโนมัติ

เปิด ArcGIS Pro ใหม่ → bridge ขึ้นเอง (`autoLoad="true"`) → แท็บ **MCP** บน ribbon
มีปุ่ม Start / Stop / Status

ถ้า Pro ติดตั้งไว้ที่อื่น: `-p:ArcGISProDir="D:\ArcGIS\Pro"`

## โครงสร้าง

```
addin/ArcGISProMCP/
├── ArcGISProMCP.csproj    # อ้างอิง assembly จาก Pro โดยตรง + targets ของ Esri
├── Config.daml            # นิยาม add-in, autoLoad, ribbon
├── MCPModule.cs           # lifecycle + auto-start
├── Bridge/
│   ├── Protocol.cs        # wire format + ตัวอ่าน params
│   ├── BridgeServer.cs    # TCP listener + instance discovery file
│   ├── CommandRouter.cs   # dispatch + marshal เข้า MCT
│   └── PythonFallback.cs  # ส่งต่อคำสั่งที่ไม่รู้จักไป Python
├── Commands/              # คำสั่งที่ทำใน C# แล้ว
└── UI/Buttons.cs          # ปุ่มบน ribbon
```

## สถานะ

ทดสอบกับ ArcGIS Pro 3.7.1 จริงแล้ว — **109 จาก 112 คำสั่งอยู่ใน add-in**,
latency 9ms (เทียบกับ ~28 วินาทีของฝั่ง Python)

อีก 3 ตัวอยู่ฝั่ง Python และ**ควรอยู่ตรงนั้น**:

| คำสั่ง | ทำไมไม่ย้าย |
|---|---|
| `execute_arcpy_code` | add-in ที่ compile แล้วรันโค้ดที่แต่งขึ้นตอนนั้นไม่ได้ |
| `get_pump_status` | มันรายงานสถานะ dispatcher **ของฝั่ง Python** ซึ่งมีอยู่จริงแค่ที่นั่น |
| `stop_pump` | เช่นเดียวกัน — add-in ไม่มี pump ให้หยุด มันใช้ MCT ตรง ๆ |

`run_geoprocessing_tool` รับ named parameters ได้แล้ว โดยใช้ตารางลำดับ
parameter ของ ~2,000 tool ที่ดึงจาก arcpy (`scripts/dump_gp_parameters.py`)
แล้วฝังไว้ — Pro SDK เองไม่มี API บอกชื่อ parameter ของ tool

### สิ่งที่ต้องระวังตอนใช้

- layer ที่อยู่ใน group ต้องเรียกด้วยชื่อเต็ม `"ชื่อกลุ่ม\ชื่อ layer"` เวลาส่งให้
  คำสั่งที่วิ่งผ่าน geoprocessing (`add_fields`, `apply_symbology_from_layer`,
  `calculate_field` ฯลฯ) ไม่งั้นจะได้ `ERROR 000732: Dataset does not exist`
- `duplicate_layer` ทำสำเนา **layer** ไม่ใช่ข้อมูล — ทั้งสอง layer ชี้ dataset
  เดียวกัน การ `add_fields` บนสำเนาจึงแก้ไฟล์ต้นทางจริง
