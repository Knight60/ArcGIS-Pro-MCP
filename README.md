# ArcGIS Pro MCP

MCP (Model Context Protocol) server สำหรับให้ AI assistant — **Claude Code**,
**OpenAI Codex CLI** และ **Gemini CLI** — ควบคุม **ArcGIS Pro ที่เปิดอยู่จริง**:
ดู/จัดการ layer, query ข้อมูล attribute, รันเครื่องมือ geoprocessing,
ปรับ symbology, export แผนที่และ layout รวมถึงรันโค้ด arcpy ใดก็ได้

> MCP server that lets AI assistants (Claude Code, Codex, Gemini CLI) control
> a live ArcGIS Pro session through arcpy.

## สถาปัตยกรรม

```
Claude Code / Codex / Gemini CLI
        │  MCP (stdio)
        ▼
arcgis-pro-mcp  (แพ็กเกจนี้ — รันบน Python ≥3.10 ทั่วไป ไม่ต้องมี arcpy)
        │  JSON over TCP (localhost:6510)
        ▼
MCP Bridge  (arcgis_pro_plugin/ — รัน "ภายใน" ArcGIS Pro ผ่าน Python Toolbox
             จึงเข้าถึงโปรเจกต์ที่เปิดอยู่ผ่าน arcpy ได้เต็มรูปแบบ)
```

ต้องแบ่งเป็น 2 ส่วน เพราะ arcpy จะเข้าถึงโปรเจกต์ที่ **เปิดอยู่** (`"CURRENT"`)
ได้เฉพาะจาก Python runtime ภายใน ArcGIS Pro เท่านั้น

| ส่วน | รันที่ไหน | โฟลเดอร์ |
|---|---|---|
| MCP server | Python 3.10+ ทั่วไป (ไม่ต้องมี arcpy) | `src/arcgis_pro_mcp/` |
| Bridge plugin | ภายใน ArcGIS Pro (Python Toolbox) | `arcgis_pro_plugin/` |

## การติดตั้ง

### 1. ติดตั้ง plugin ฝั่ง ArcGIS Pro

1. เปิด ArcGIS Pro พร้อมโปรเจกต์ของคุณ
2. ไปที่หน้าต่าง **Catalog** → คลิกขวา **Toolboxes** → **Add Toolbox** →
   เลือกไฟล์ `arcgis_pro_plugin/ArcGISMCP.pyt` จาก repo นี้
3. รันเครื่องมือ **Start MCP Server** (พอร์ตเริ่มต้น 6510)
4. เปิด ArcGIS Pro ทิ้งไว้ตลอดการใช้งาน — server จะหยุดเมื่อปิด Pro
   ดังนั้นเปิด Pro ใหม่เมื่อไหร่ต้องรัน **Start MCP Server** อีกครั้ง

ทางเลือก (ไม่ใช้ toolbox): วางโค้ดนี้ใน **Python window** ของ Pro

```python
import sys; sys.path.insert(0, r"D:\Developing\ArcGIS-MCP\arcgis_pro_plugin")
import mcp_bridge; print(mcp_bridge.start_server())
```

### 2. ติดตั้ง MCP server

ใช้ Python ≥3.10 ตัวไหนก็ได้ในเครื่อง (ไม่จำเป็นต้องเป็น Python ของ ArcGIS Pro)
จากโฟลเดอร์ repo นี้:

```powershell
pip install -e .
```

หรือใช้ [uv](https://docs.astral.sh/uv/) โดยไม่ต้องติดตั้ง — ใช้คำสั่ง
`uv run --directory D:\Developing\ArcGIS-MCP arcgis-pro-mcp` แทนในขั้นตอนถัดไป

### 3. ลงทะเบียนกับ AI client ที่ใช้

> ตัวอย่างด้านล่างใช้ `python -m arcgis_pro_mcp` ซึ่งใช้ได้เสมอ
> (ถ้า `arcgis-pro-mcp.exe` อยู่ใน PATH จะใช้ `"command": "arcgis-pro-mcp"` เฉย ๆ ก็ได้)

**Claude Code** — repo นี้มี [.mcp.json](.mcp.json) ให้แล้ว ใช้ได้ทันทีเมื่อเปิด
Claude Code ในโฟลเดอร์นี้ หรือลงทะเบียนแบบ global:

```powershell
claude mcp add arcgis --scope user -- python -m arcgis_pro_mcp
```

หรือเขียนเองใน `.mcp.json` (ระดับโปรเจกต์) / `~/.claude.json` (ทุกโปรเจกต์):

```json
{
  "mcpServers": {
    "arcgis": {
      "command": "python",
      "args": ["-m", "arcgis_pro_mcp"]
    }
  }
}
```

**OpenAI Codex CLI** — เพิ่มใน `~/.codex/config.toml`:

```toml
[mcp_servers.arcgis]
command = "python"
args = ["-m", "arcgis_pro_mcp"]
```

**Gemini CLI** — เพิ่มใน `~/.gemini/settings.json`
(หรือ `.gemini/settings.json` ในโปรเจกต์):

```json
{
  "mcpServers": {
    "arcgis": {
      "command": "python",
      "args": ["-m", "arcgis_pro_mcp"]
    }
  }
}
```

### 4. ทดสอบ

เปิด ArcGIS Pro + รัน Start MCP Server แล้วลองถาม AI ว่า:

> "ping ArcGIS แล้วบอกหน่อยว่าโปรเจกต์ที่เปิดอยู่มี layer อะไรบ้าง"

## ตัวแปร environment (ไม่บังคับ)

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `ARCGIS_MCP_HOST` | `127.0.0.1` | host ของ bridge |
| `ARCGIS_MCP_PORT` | `6510` | พอร์ตของ bridge (ต้องตรงกับที่ตั้งใน Start MCP Server) |
| `ARCGIS_MCP_TIMEOUT` | `300` | วินาทีที่รอ geoprocessing ที่ใช้เวลานาน |

## Tools ทั้งหมด (31 ตัว)

### Session / โปรเจกต์
| Tool | หน้าที่ |
|---|---|
| `ping` | เช็คว่าเชื่อมต่อ bridge ใน ArcGIS Pro ได้ |
| `get_arcgis_info` | เวอร์ชัน Pro, license, path โปรเจกต์ |
| `get_project_info` | รายละเอียดโปรเจกต์: gdb เริ่มต้น, maps, layouts |
| `list_maps` | รายชื่อ map ทั้งหมดพร้อม CRS และจำนวน layer |
| `create_map` | สร้าง map ใหม่ (MAP หรือ SCENE) |
| `save_project` | บันทึกโปรเจกต์ (.aprx) |

### Layer
| Tool | หน้าที่ |
|---|---|
| `get_layers` | รายชื่อ layer และ table ใน map |
| `add_layer` | เพิ่มข้อมูลจาก path/URL (feature class, shapefile, raster, .lyrx, service) |
| `remove_layer` | ลบ layer ออกจาก map |
| `set_layer_visibility` | เปิด/ปิดการแสดง layer |
| `set_definition_query` | ตั้ง definition query (SQL) ให้ layer |
| `get_layer_info` | รายละเอียด layer: source, CRS, extent, fields, จำนวน feature |
| `zoom_to_layer` | ซูมไปยัง extent ของ layer |
| `set_basemap` | เปลี่ยน basemap เช่น Imagery, Topographic |

### ข้อมูล attribute
| Tool | หน้าที่ |
|---|---|
| `get_features` | อ่าน feature (where clause, เลือก field, geometry เป็น WKT ได้) |
| `get_unique_values` | ค่าที่ไม่ซ้ำของ field |
| `get_field_statistics` | min / max / mean / sum / std ของ field ตัวเลข |
| `select_features` | select ด้วย SQL (NEW / ADD / REMOVE / SUBSET) |
| `clear_selection` | ล้าง selection ของ layer เดียวหรือทั้ง map |

### Schema / แก้ไขข้อมูล
| Tool | หน้าที่ |
|---|---|
| `add_field` | เพิ่ม field (TEXT, LONG, DOUBLE, DATE, …) |
| `delete_field` | ลบ field |
| `calculate_field` | คำนวณค่า field (PYTHON3 / ARCADE / SQL) |
| `create_feature_class` | สร้าง feature class ใหม่ใน gdb |

### Geoprocessing
| Tool | หน้าที่ |
|---|---|
| `run_geoprocessing_tool` | รัน arcpy tool ใดก็ได้ เช่น `analysis.Buffer`, `management.Clip` |
| `list_geoprocessing_tools` | ค้นหา tool ด้วย wildcard เช่น `Clip*` |

### Symbology / Export
| Tool | หน้าที่ |
|---|---|
| `set_layer_renderer` | เปลี่ยน symbology: simple (สี RGB), unique values, graduated colors |
| `list_layouts` | รายชื่อ layout ในโปรเจกต์ |
| `export_layout` | export layout เป็น PDF / PNG / JPEG / SVG |
| `export_map_view` | export map view เป็น PNG (ให้ AI "เห็น" แผนที่ได้) |

### Raster / อื่น ๆ
| Tool | หน้าที่ |
|---|---|
| `get_raster_info` | ข้อมูล raster: จำนวน band, ขนาด, cell size, สถิติ |
| `execute_arcpy_code` | รันโค้ด Python ใดก็ได้ภายใน ArcGIS Pro (arcpy พร้อมใช้) |

## ตัวอย่าง prompt

- "What layers are in my current map and how many features does each have?"
- "Buffer ชั้นข้อมูลถนน 500 เมตร แล้วเพิ่มผลลัพธ์ลงแผนที่"
- "ลงสีชั้นข้อมูลจังหวัดตาม field POP แบบ graduated 5 คลาส ใช้ color ramp Viridis"
- "export map view เป็น PNG แล้วดูให้หน่อยว่าแผนที่เป็นยังไง"
- "สรุปจำนวน feature แยกตามชนิดป่าใน layer forest_type"

## โปรโตคอลภายใน (สำหรับผู้พัฒนา)

Bridge ใช้ newline-delimited JSON ผ่าน TCP:

```
request : {"id": 1, "command": "get_layers", "params": {"map_name": null}}\n
response: {"id": 1, "success": true, "data": {...}}\n
error   : {"id": 1, "success": false, "error": "...", "traceback": "..."}\n
```

เพิ่มคำสั่งใหม่ได้โดยเขียนฟังก์ชัน handler ใน
[mcp_bridge.py](arcgis_pro_plugin/mcp_bridge.py) + ลงทะเบียนใน `HANDLERS`
แล้วเพิ่ม `@mcp.tool()` ที่เรียก `_call()` ใน
[server.py](src/arcgis_pro_mcp/server.py)

## ข้อควรระวังด้านความปลอดภัย

- Bridge รับเฉพาะ **localhost** แต่โปรเซสใดก็ได้ในเครื่องเชื่อมต่อได้ และ
  `execute_arcpy_code` / `run_geoprocessing_tool` แก้ไขหรือลบข้อมูลได้จริง —
  เปิด server เฉพาะตอนใช้งาน บนเครื่องที่เชื่อถือได้เท่านั้น
- AI ทำงานกับ **โปรเจกต์จริงที่เปิดอยู่** — ควร save/backup ก่อนให้แก้ไขข้อมูลจำนวนมาก

## แก้ปัญหาเบื้องต้น

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| "Cannot connect to ArcGIS Pro MCP bridge" | ยังไม่ได้เปิด ArcGIS Pro, ยังไม่ได้รัน Start MCP Server, หรือพอร์ตไม่ตรงกับ `ARCGIS_MCP_PORT` |
| Tool ค้างนาน | geoprocessing ใช้เวลานาน — เพิ่มค่า `ARCGIS_MCP_TIMEOUT` |
| "Layer not found" | ใช้ชื่อ layer ตรงตามที่ `get_layers` แสดง (layer ใน group ใช้ long name แบบ `Group\Layer`) |
| แก้โค้ด bridge แล้วไม่มีผล | รันเครื่องมือใดก็ได้ใน toolbox หนึ่งครั้งเพื่อ reload โมดูล (server ที่รันอยู่ไม่หลุด) |

## โครงสร้าง repo

```
ArcGIS-MCP/
├── arcgis_pro_plugin/
│   ├── ArcGISMCP.pyt        # Python Toolbox: Start / Stop / Status
│   └── mcp_bridge.py        # socket server + handler 31 คำสั่ง (รันใน Pro)
├── src/arcgis_pro_mcp/
│   ├── server.py            # FastMCP stdio server (31 tools)
│   └── connection.py        # TCP client + auto-reconnect
├── .mcp.json                # config สำเร็จรูปสำหรับ Claude Code
├── pyproject.toml
└── README.md
```
