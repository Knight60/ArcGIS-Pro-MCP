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

## สถาปัตยกรรม

```
AI client ──MCP──► arcgis-pro-mcp (Python, ไม่ต้องแก้)
                        │ JSON over TCP :6510
                        ▼
              ┌─ C# Add-in (ในโปรเซส Pro) ─────────────┐
              │  socket thread → QueuedTask.Run (MCT)  │
              │  คำสั่งที่ไม่รู้จัก ─┐                  │
              └────────────────────┼───────────────────┘
                                   ▼ :6511
                        Python bridge (arcpy escape hatch)
```

**protocol เหมือนเดิมทุกอย่าง** — newline-delimited JSON เดิม ฝั่ง MCP server,
tool catalog, tests และ CLI ใช้ต่อได้โดยไม่ต้องแก้

คำสั่งที่ add-in ยังไม่ได้ทำ จะถูกส่งต่อไป Python bridge อัตโนมัติ ทำให้
`execute_arcpy_code` และ handler อีก ~80 ตัวยังใช้ได้ระหว่างที่ทยอยย้าย

## ต้องมีอะไรบ้าง

| | ตอนพัฒนา | ตอนใช้งาน |
|---|---|---|
| ArcGIS Pro 3.5+ | ✅ | ✅ |
| .NET 8 SDK | ✅ | ❌ |
| Visual Studio | ไม่บังคับ (ใช้ `dotnet build` ได้) | ❌ |
| ArcGIS Pro SDK for .NET | เฉพาะเพื่อแพ็ก `.esriAddinX` | ❌ |

ผู้ใช้ปลายทางแค่ดับเบิลคลิกไฟล์ `.esriAddinX` ครั้งเดียว

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

ยังไม่เคย build (เครื่องพัฒนายังไม่มี .NET 8 SDK) — โค้ดนี้ยังไม่ผ่าน compiler
สักครั้ง คาดว่าต้องมีรอบแก้ compile error ก่อนใช้งานได้จริง

คำสั่งที่ทำใน C# แล้ว: session/project/maps, layers, data read + summarize,
selection, view + export image, geoprocessing (แบบ positional args)

ที่เหลือยังวิ่งผ่าน Python fallback: symbology, labels, layouts, bookmarks,
raster, schema, editing, catalog และ `execute_arcpy_code`

`run_geoprocessing_tool` แบบ named parameters ยังส่งต่อไป Python เพราะ Pro SDK
รับเฉพาะ positional — ต้องหาวิธี resolve ลำดับ parameter จาก metadata ก่อน
