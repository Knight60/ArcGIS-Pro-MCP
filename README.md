# ArcGIS Pro MCP

MCP (Model Context Protocol) server สำหรับให้ AI assistant — **Claude Code**,
**OpenAI Codex CLI** และ **Gemini CLI** — ควบคุม **ArcGIS Pro ที่เปิดอยู่จริง**
ได้เกือบทุกอย่างที่ทำผ่านหน้าจอได้: จัดการ layer, query และแก้ไขข้อมูล,
รัน geoprocessing ทุกตัว, ทำ symbology/label, สร้าง layout, export แผนที่
และ **ดูภาพแผนที่ที่ได้** เพื่อปรับต่อเอง

> MCP server that lets AI assistants drive a live ArcGIS Pro session:
> 110 dedicated tools plus unrestricted access to arcpy.

## ทำอะไรได้บ้าง

| ระดับ | เครื่องมือ | ครอบคลุม |
|---|---|---|
| Tool เฉพาะทาง | 110 tools | layer, ข้อมูล, selection, schema, symbology, label, layout, bookmark, raster, ค้นหาข้อมูล |
| Geoprocessing ทั้งหมด | `run_geoprocessing_tool` + `describe_geoprocessing_tool` | เครื่องมือ arcpy ~2,000 ตัว — AI อ่านพารามิเตอร์ของ tool เองได้ก่อนเรียก |
| ไม่มีขีดจำกัด | `execute_arcpy_code` | โค้ด Python ใด ๆ ใน Pro (ตัวแปรค้างข้ามการเรียก) |

จุดที่ทำให้ AI ทำงานได้เองจริง ๆ:

- **มองเห็นแผนที่** — `export_map_view` / `preview_layout` ส่งภาพ PNG กลับมา
  ให้ AI ดูแล้วแก้สี/scale/label ต่อได้เอง
- **หาข้อมูลเองได้** — `search_data`, `list_workspace_contents`, `list_folder`,
  `describe_dataset` ค้นชุดข้อมูลใน gdb/โฟลเดอร์โดยไม่ต้องเพิ่มเข้าแผนที่ก่อน
- **รู้จัก tool ที่ยังไม่เคยใช้** — `describe_geoprocessing_tool` คืนพารามิเตอร์
  ชนิดข้อมูล ค่า default และ usage ของ arcpy tool ทุกตัว
- **แก้ปัญหาเองได้** — `diagnose` บอกว่าติดตรงไหน (ไม่มี active map,
  ไม่ได้เปิด map view, ไม่มีสิทธิ์เขียน ฯลฯ) และข้อความ error ทุกอันมี Hint
- **เร็วขึ้น** — `run_batch` ยิงหลายคำสั่งใน round trip เดียว

## สถาปัตยกรรม

```
Claude Code / Codex / Gemini CLI
        │  MCP (stdio)
        ▼
arcgis-pro-mcp  (แพ็กเกจนี้ — Python ≥3.10 ทั่วไป ไม่ต้องมี arcpy)
        │  JSON over TCP (localhost:6510, ค้นพอร์ตอัตโนมัติ)
        ▼
┌─ ภายใน ArcGIS Pro ──────────────────────────────────────────┐
│  socket thread     → queue + PostMessage →  message loop     │
│  (รับ JSON, ไม่แตะ arcpy)              ของ ArcGIS Pro เอง     │
│                    ←     result      ←  รัน handler บน main  │
└─────────────────────────────────────────────────────────────┘
```

แบ่งเป็น 2 ฝั่งเพราะ arcpy เข้าถึงโปรเจกต์ที่ **เปิดอยู่** (`"CURRENT"`) ได้
เฉพาะจาก Python runtime ภายใน ArcGIS Pro

| ส่วน | รันที่ไหน | โฟลเดอร์ |
|---|---|---|
| MCP server | Python 3.10+ ทั่วไป (ไม่ต้องมี arcpy) | `src/arcgis_pro_mcp/` |
| Bridge plugin | ภายใน ArcGIS Pro (Python Toolbox) | `arcgis_pro_plugin/` |

### ทำไมต้องมี main-thread pump

ทดสอบบน ArcGIS Pro 3.5.2 แล้วพบว่า `arcpy.mp.ArcGISProject("CURRENT")`
**ทำงานได้เฉพาะบน main thread ของ Pro เท่านั้น**:

| ทดสอบ | ผล |
|---|---|
| เรียกจาก background thread | `OSError: CURRENT` เสมอ |
| `pythoncom.CoInitialize` STA / MTA ก่อนเรียก | ไม่ช่วย |
| เปิด `.aprx` ด้วย path จาก background thread | สำเร็จ แต่ได้ **สำเนาแยกของไฟล์ที่เซฟไว้** — เปิด 2 ครั้งได้ 2 object อิสระ, `camera.scale` = 0.0 |
| เรียกจาก Python window | สำเร็จ (Python window = MainThread) |

socket server จำเป็นต้องอยู่บน background thread ดังนั้น bridge จึงแยกหน้าที่:
thread รับ JSON ส่งงานเข้า queue แล้ว **PostMessage ไปหา message-only window
ที่สร้างไว้บน main thread** — message loop ของ ArcGIS Pro เองเป็นคนเรียก
WndProc ของเรากลับมาบน main thread แล้วรัน handler (`arcgis_mcp/pump.py`)

**จุดสำคัญคือ dispatcher ไม่ยึด main thread เลย** สองดีไซน์ก่อนหน้ายึดไว้และ
ทำให้ Pro ค้างทั้งคู่ — ทั้ง sleep loop + `PumpWaitingMessages()` และ
`GetMessage`/`DispatchMessage` loop เต็มรูปแบบ เพราะ **ArcGIS Pro ปิดการใช้งาน
map view ตลอดเวลาที่ cell ใน Python window ยังทำงานอยู่** ไม่ว่าจะ dispatch
message ครบแค่ไหน ทางแก้จึงต้องเลิกยึด Python window ไปเลย

คำสั่งที่ไม่ต้องใช้โปรเจกต์ที่เปิดอยู่ — geoprocessing ตาม path,
`describe_dataset`, `list_workspace_contents` — ยังทำงานได้แม้ไม่มี pump

### ข้อสังเกตอื่นจากการทดสอบบน Pro 3.5.2

สามข้อนี้ทำให้โค้ดที่ดู "ถูกต้อง" ทำงานผิดแบบเงียบ ๆ จึงบันทึกไว้:

| เรื่อง | สิ่งที่พบ | ทางแก้ในโค้ด |
|---|---|---|
| `Map.defaultView` | เป็น view คนละตัวกับที่ผู้ใช้เห็น — `exportToPNG` ใช้ได้ แต่สั่ง `camera.setExtent()` แล้ว UI ไม่ขยับ และ `camera.scale` อ่านได้ `0.0` | ใช้ `project.activeView` แทน (`common.live_view`) |
| `Layout.createTextElement` / `createPictureElement` | **ไม่มีใน Pro 3.x** (มีแค่ `createMapFrame`, `createMapSurroundElement`, `createTableFrameElement`) | ประกอบ `CIMGraphicElement` + `CIMTextGraphic`/`CIMPictureGraphic` เองแล้ว `setDefinition` |
| `add_to_map` | Pro เพิ่ม output ของ geoprocessing เข้าแผนที่ให้เองอยู่แล้ว การเพิ่มซ้ำทำให้ได้ layer ชื่อเดียวกัน 2 อัน | `common.add_layer_once()` เช็ค data source ก่อน และ `remove_layer` ลบทุกอันที่ชื่อตรง |

## ติดตั้ง

### เร็วที่สุด: C# add-in + MCP over HTTP

ถ้าใช้ [add-in](addin/) (แนะนำ — เร็วกว่าฝั่ง Python ~3,000 เท่า และไม่ต้องสั่งอะไร
ตอนเปิด Pro):

```powershell
dotnet build addin\ArcGISProMCP\ArcGISProMCP.csproj -c Release
claude mcp add --transport http arcgis http://127.0.0.1:6520/mcp
```

restart ArcGIS Pro แล้วใช้ได้เลย ไม่ต้องมี Python สำหรับงานหลัก
รายละเอียดใน [addin/README.md](addin/README.md)

ส่วนที่เหลือของหน้านี้เป็นทางฝั่ง Python ซึ่งยังใช้ได้และจำเป็นถ้าต้องการ
`execute_arcpy_code`

### วิธีเร็วที่สุด (ฝั่ง Python)

```powershell
.\install.ps1
```

สคริปต์จะ: ตรวจ Python → `pip install -e .` → ลงทะเบียน MCP ให้กับ client ที่
เจอในเครื่อง (Claude Code / Codex / Gemini — สำรองไฟล์ config เป็น `.bak` ก่อนแก้)
→ ติดตั้ง **auto-start** ให้ bridge ขึ้นเองเมื่อเปิด ArcGIS Pro

> auto-start ต้องเขียนไฟล์ลง Python environment ของ Pro
> (`...\arcgispro-py3\Lib\site-packages`) ซึ่งอยู่ใน Program Files —
> **ต้องรัน PowerShell แบบ Run as administrator** ถ้าไม่ได้รันแบบ admin
> สคริปต์จะข้ามส่วนนี้แล้วบอกวิธีใช้ toolbox แทน (ไม่ error)

ตัวเลือก:

```powershell
.\install.ps1 -Clients claude              # ลงทะเบียนเฉพาะ Claude Code
.\install.ps1 -Clients none                # ไม่แตะ config ของ client
.\install.ps1 -NoAutoStart                 # ไม่ติดตั้ง auto-start
.\install.ps1 -Python C:\Python313\python.exe
.\install.ps1 -ProPython "C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
.\install.ps1 -Uninstall                   # ถอน auto-start ออก
```

### Auto-start ทำงานยังไง

ติดตั้ง 2 ไฟล์ลง site-packages ของ Pro: `arcgis_mcp_autostart.py` กับไฟล์ `.pth`
ที่ import มันตอน Python เริ่มทำงาน

`.pth` จะถูกรันใน **ทุก** process ที่ใช้ env นี้ (รวม background geoprocessing)
โมดูลจึงมีด่านกัน 2 ชั้น:

1. เช็คชื่อ executable ว่าเป็น `ArcGISPro.exe` ก่อน — ถ้าไม่ใช่ ออกทันที
   **ไม่ import arcpy** (วัดจริงบน Pro 3.5.2: 0.3 วินาที ไม่กระทบ process อื่น)
2. ใน daemon thread รอจนกว่า `arcpy.mp.ArcGISProject("CURRENT")` จะสำเร็จ —
   ซึ่งเป็นจริงเฉพาะภายในแอป Pro เท่านั้น แล้วจึง start bridge

error ทุกอย่างถูกกลืนและเขียน log ไว้ที่
`%LOCALAPPDATA%\ArcGIS-MCP\autostart.log` — เปิด Pro ไม่พังแน่นอน

ปิดชั่วคราวได้โดยแก้ `%LOCALAPPDATA%\ArcGIS-MCP\autostart.json` เป็น
`"enabled": false`

### ถ้าไม่ใช้ auto-start (หรือติดตั้งไม่ได้)

1. เปิด ArcGIS Pro พร้อมโปรเจกต์ของคุณ
2. **Catalog** → คลิกขวา **Toolboxes** → **Add Toolbox** →
   เลือก `arcgis_pro_plugin/ArcGISMCP.pyt`
3. รันเครื่องมือ **Start MCP Server** (พอร์ตเริ่มต้น 6510 — ถ้าไม่ว่างจะเลื่อนไปพอร์ตถัดไปให้เอง)

toolbox จะถูกจำไว้ในไฟล์ `.aprx` ครั้งต่อไปแค่รัน **Start MCP Server** อีกครั้ง
(server จะหยุดเมื่อปิด Pro)

ทางเลือก — วางใน **Python window** ของ Pro:

```python
import sys; sys.path.insert(0, r"D:\Developing\ArcGIS-MCP\arcgis_pro_plugin")
import mcp_bridge; print(mcp_bridge.start_server())
```

### ติดตั้ง main-thread dispatcher (จำเป็น)

หลัง bridge ขึ้นแล้ว วางบรรทัดนี้ใน **Python window** ของ ArcGIS Pro หนึ่งครั้ง:

```python
import mcp_bridge; mcp_bridge.start_pump()
```

**คำสั่งนี้จบทันที** ไม่ค้าง cell ไว้ — ArcGIS Pro ทำงานตามปกติทุกอย่าง
ถอนออกได้ด้วย tool `stop_pump` หรือ `python -m arcgis_pro_mcp stop-pump`

ถ้าไม่ติดตั้ง คำสั่งที่แตะโปรเจกต์ที่เปิดอยู่จะ error พร้อมบอกวิธีติดตั้ง
ส่วน `ping`, `get_capabilities`, `get_pump_status`, `stop_pump` และงานที่อิง
path ล้วน ๆ ยังใช้ได้

### ตรวจสอบว่าใช้ได้

```powershell
python -m arcgis_pro_mcp doctor
```

จะบอกว่าเจอ bridge ไหม เชื่อมต่อได้ไหม โปรเจกต์ไหนเปิดอยู่ มี active map /
map view หรือยัง

คำสั่ง CLI อื่น:

```powershell
python -m arcgis_pro_mcp tools     # รายการ tool ทั้งหมด
python -m arcgis_pro_mcp setup     # snippet config สำหรับ client แต่ละตัว
```

### ติดตั้งเอง (ไม่ใช้สคริปต์)

```powershell
pip install -e .
```

**Claude Code** — repo นี้มี [.mcp.json](.mcp.json) ให้แล้ว หรือลงทะเบียนแบบ global:

```powershell
claude mcp add arcgis --scope user -- python -m arcgis_pro_mcp
```

**OpenAI Codex CLI** — `~/.codex/config.toml`:

```toml
[mcp_servers.arcgis]
command = "python"
args = ["-m", "arcgis_pro_mcp"]
```

**Gemini CLI** — `~/.gemini/settings.json`:

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

## ตัวอย่าง prompt

- "โปรเจกต์ที่เปิดอยู่มี layer อะไรบ้าง แต่ละอันมีกี่ feature"
- "หาข้อมูลถนนใน gdb ของโปรเจกต์ เพิ่มเข้าแผนที่ แล้ว buffer 500 เมตร"
- "ลงสีชั้นจังหวัดตาม POP แบบ graduated 5 คลาส ramp Viridis แล้ว export ภาพมาให้ดู"
- "ทำ layout A4 แนวนอน มี legend, scale bar, ลูกศรทิศเหนือ, ชื่อเรื่อง แล้ว export PDF"
- "เลือกแปลงที่อยู่ในระยะ 1 กม. จากแม่น้ำ แล้วสรุปพื้นที่รวมแยกตามตำบล"
- "layer ไหนขาด source บ้าง ซ่อมให้หน่อย"
- "ใส่ label ชื่อจังหวัด ฟอนต์ 10pt มี halo แล้วเช็คภาพว่าอ่านออกไหม"

### Prompt สำเร็จรูป (MCP prompts)

| Prompt | ใช้ทำอะไร |
|---|---|
| `explore_project` | สำรวจโปรเจกต์แล้วสรุปว่ามีอะไร พร้อมชี้จุดที่ผิดปกติ |
| `make_map` | ทำแผนที่พร้อม export ตั้งแต่ symbology จนถึง layout PDF |
| `analyze` | ตอบคำถามเชิงพื้นที่ด้วยข้อมูลในโปรเจกต์ |

### Resource

| Resource | เนื้อหา |
|---|---|
| `arcgis://tools` | รายการ tool ทั้งหมดแยกตามกลุ่ม |
| `arcgis://status` | สถานะ bridge และโปรเจกต์ที่เปิดอยู่ |
| `arcgis://project` | สรุปโปรเจกต์ปัจจุบัน |

## Tools

<!-- TOOLS:START -->

รวม **112 tools** — และทุกอย่างที่เหลือเข้าถึงได้ผ่าน `run_geoprocessing_tool` / `execute_arcpy_code`

### Session / โปรเจกต์ (14)

| Tool | หน้าที่ |
|---|---|
| `ping` | Check that the ArcGIS Pro bridge is reachable and see which project it is attached to |
| `get_capabilities` | List every command the connected bridge supports, grouped by area |
| `diagnose` | Self-check the connection: ArcGIS Pro version, licence, open project, active map, open map view and write access |
| `get_arcgis_info` | ArcGIS Pro version, licence level, available extensions and the current project path |
| `get_project_info` | Project paths, default geodatabase and toolbox, maps, layouts, folder and database connections |
| `save_project` | Save the ArcGIS Pro project (.aprx), or save a copy elsewhere |
| `list_maps` | List all maps and scenes with coordinate system and layer counts |
| `create_map` | Create a new map or scene in the project |
| `remove_map` ⚠️ | Delete a map from the project |
| `activate_map` | Open/activate a map's view in the ArcGIS Pro UI |
| `set_map_properties` | Rename a map or change its coordinate system |
| `get_map_extent` | The combined extent of all data layers in a map |
| `get_environment` | Read the current arcpy geoprocessing environment settings |
| `set_environment` | Set arcpy geoprocessing environment settings such as workspace, outputCoordinateSystem, extent, mask, cellSize, overwriteOutput or parallelProcessingFactor |

### Layer (19)

| Tool | หน้าที่ |
|---|---|
| `get_layers` | List the layers (with draw order and group nesting) and standalone tables in a map |
| `get_layer_info` | Full detail for one layer: data source, coordinate system, extent, fields, feature count, renderer and label state |
| `add_layer` | Add data to a map from a path or service URL: feature class, shapefile, raster, table, .lyrx layer file or web service |
| `add_web_layer` | Add a web service layer (Feature/Map/Image service, WMS, WMTS, vector tile) by URL |
| `remove_layer` ⚠️ | Remove a layer or standalone table from a map |
| `rename_layer` | Rename a layer in the table of contents |
| `duplicate_layer` | Copy a layer within the map so it can be symbolised differently |
| `set_layer_visibility` | Show or hide one layer, several layers, or every layer in the map |
| `set_layer_transparency` | Set layer transparency (0 = opaque, 100 = fully transparent) |
| `set_layer_scale_range` | Limit the scale range a layer draws at |
| `set_definition_query` | Set a layer's definition query (SQL where clause) |
| `move_layer` | Reorder a layer relative to another, or move it into a group layer |
| `create_group_layer` | Create a group layer, optionally moving existing layers into it |
| `zoom_to_layer` | Zoom the map view to a layer's extent |
| `set_basemap` | Set the basemap: Topographic, Imagery, Imagery Hybrid, Streets, Navigation, Light Gray Canvas, Dark Gray Canvas, Terrain, Oceans, OpenStreetMap, National Geographic Style Map |
| `get_broken_layers` | List layers across all maps whose data source is missing |
| `repair_layer_source` | Repoint a layer at a new workspace or dataset to fix a broken source |
| `add_join` | Join a table to a layer on a common field |
| `remove_join` | Remove a join from a layer |

### ข้อมูล attribute และการแก้ไข (11)

| Tool | หน้าที่ |
|---|---|
| `get_features` | Read attribute rows from a layer, table or dataset path, with an optional where clause, field subset, ordering and WKT geometry |
| `count_features` | Count features, optionally matching a where clause |
| `get_unique_values` | Distinct values of a field with the count of rows for each |
| `get_field_statistics` | min / max / mean / median / sum / standard deviation of a numeric field |
| `summarize_features` | Group rows by one or more fields and aggregate -- the fast way to answer 'how many / how much per category' without geoprocessing |
| `insert_features` | Insert new rows into a layer or table |
| `update_features` ⚠️ | Update attributes and/or geometry of rows matching a where clause |
| `delete_features` ⚠️ | Delete rows matching a where clause |
| `save_edits` | Commit pending edits |
| `discard_edits` | Throw away pending edits |
| `calculate_field` | Calculate field values across a layer, e.g |

### Selection (6)

| Tool | หน้าที่ |
|---|---|
| `select_features` | Select features by SQL where clause |
| `select_by_location` | Select features by spatial relationship to another layer |
| `get_selection` | Report what is currently selected, per layer, with ObjectIDs and optionally the attribute rows |
| `set_selection` | Select specific features by ObjectID |
| `clear_selection` | Clear the selection on one layer, or on every layer in the map |
| `zoom_to_selection` | Zoom the map view to the currently selected features |

### Schema / สร้างชุดข้อมูล (11)

| Tool | หน้าที่ |
|---|---|
| `list_fields` | List a layer's fields with type, alias, length and domain |
| `add_field` | Add a field to a layer or table |
| `add_fields` | Add several fields in one call |
| `delete_field` ⚠️ | Delete one or more fields |
| `alter_field` | Rename a field or change its alias/length |
| `create_feature_class` | Create an empty feature class, by default in the project's default geodatabase, and add it to the map |
| `create_table` | Create an empty standalone table |
| `create_file_geodatabase` | Create a new file geodatabase |
| `truncate_table` ⚠️ | Delete every row from a table or feature class, keeping the schema |
| `delete_dataset` ⚠️ | Delete a dataset from disk or a geodatabase |
| `export_features` | Export a layer -- honouring its current selection and definition query -- to a new dataset |

### Geoprocessing (7)

| Tool | หน้าที่ |
|---|---|
| `run_geoprocessing_tool` | Run any arcpy geoprocessing tool -- the universal escape hatch for analysis |
| `list_geoprocessing_tools` | Search the available geoprocessing tools by name |
| `list_toolboxes` | List the arcpy toolbox modules and any toolboxes in the project |
| `describe_geoprocessing_tool` | Get a tool's parameters, data types, defaults and usage text before running it |
| `run_python_toolbox_tool` | Run a tool from a custom .pyt / .atbx / .tbx toolbox on disk |
| `check_extension` | Check, and optionally check out, an ArcGIS extension licence |
| `get_messages` | Messages from the most recent geoprocessing operation |

### Symbology / Label (6)

| Tool | หน้าที่ |
|---|---|
| `set_layer_renderer` | Change a layer's symbology: a single symbol, unique values by category, or a classified/continuous colour scheme by numeric field |
| `get_layer_symbology` | Inspect a layer's current renderer, class breaks, unique values and label settings |
| `list_color_ramps` | List the colour ramps available in the project |
| `set_layer_labeling` | Turn labels on or off and set the expression, font and halo |
| `apply_symbology_from_layer` | Copy symbology from a .lyrx file or another layer |
| `save_layer_file` | Save a layer with its symbology to a .lyrx file for reuse |

### มุมมองแผนที่ / Bookmark (7)

| Tool | หน้าที่ |
|---|---|
| `get_map_view` | Current camera position: centre, scale, rotation and visible extent |
| `set_map_view` | Move the map view: set an extent, a centre point, a scale and/or a rotation |
| `export_map_view` 🖼️ | Render the map view to PNG and return the image so it can be looked at -- the way to visually check a map |
| `list_bookmarks` | List the spatial bookmarks defined on a map |
| `create_bookmark` | Save the current view, or a given extent, as a named bookmark |
| `apply_bookmark` | Zoom the map view to a bookmark |
| `delete_bookmark` ⚠️ | Delete a bookmark from a map |

### Layout / แผนที่พร้อมพิมพ์ (16)

| Tool | หน้าที่ |
|---|---|
| `list_layouts` | List the print layouts with page size and element counts |
| `get_layout_info` | Inspect a layout: page setup and every element with position and size |
| `create_layout` | Create a new layout page, by default with a map frame filling it |
| `delete_layout` ⚠️ | Delete a layout from the project |
| `add_map_frame` | Add a map frame to a layout at a page position |
| `set_map_frame_extent` | Point a layout's map frame at a layer, an extent or a scale |
| `add_layout_text` | Add a text element such as a title or credits to a layout |
| `add_layout_legend` | Add a legend tied to a layout's map frame |
| `add_layout_scale_bar` | Add a scale bar tied to a layout's map frame |
| `add_layout_north_arrow` | Add a north arrow tied to a layout's map frame |
| `add_layout_picture` | Place an image such as a logo on a layout |
| `set_layout_element` | Move, resize, rename, hide or change the text of any layout element |
| `delete_layout_element` ⚠️ | Remove an element from a layout |
| `export_layout` 🖼️ | Export a layout to PDF / PNG / JPEG / SVG / TIFF |
| `preview_layout` 🖼️ | Render a layout to a temporary image and return it, without writing a file -- use it to visually check a layout while building it |
| `export_map_series` | Export a layout's map series (map book) to a multi-page PDF |

### Raster (5)

| Tool | หน้าที่ |
|---|---|
| `get_raster_info` | Raster detail: bands, size, cell size, pixel type, statistics and CRS |
| `set_raster_symbology` | Set a raster layer's colorizer and colour ramp |
| `raster_calculator` | Map algebra |
| `sample_raster_values` | Read raster cell values at map coordinates or at a point layer's features |
| `zonal_statistics` | Summarise raster values inside zone polygons and return the table |

### ค้นหาและสำรวจข้อมูล (6)

| Tool | หน้าที่ |
|---|---|
| `list_workspace_contents` | List the datasets inside a geodatabase or folder |
| `list_folder` | List GIS files and subfolders on disk |
| `describe_dataset` | Describe any dataset by path -- type, geometry, CRS, extent, fields and row count -- without adding it to a map |
| `search_data` | Find datasets by name across the project's geodatabase, home folder and folder connections |
| `get_project_items` | Folder connections, database connections and toolboxes registered in the project |
| `add_folder_connection` | Register a folder with the project so its data is easy to browse |

### Escape hatch (4)

| Tool | หน้าที่ |
|---|---|
| `execute_arcpy_code` | Run Python inside ArcGIS Pro |
| `get_pump_status` | Whether the main-thread dispatcher is installed |
| `stop_pump` | Remove the main-thread dispatcher |
| `run_batch` | Run several commands in one round trip -- much faster for multi-step workflows |

⚠️ = เปลี่ยน/ลบข้อมูลจริง &nbsp;&nbsp; 🖼️ = ส่งภาพกลับมาให้ AI ดูได้

<!-- TOOLS:END -->

## ตัวแปร environment (ไม่บังคับ)

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `ARCGIS_MCP_HOST` | `127.0.0.1` | host ของ bridge |
| `ARCGIS_MCP_PORT` | `6510` | พอร์ตของ bridge — ถ้าตั้งค่านี้ จะ **ไม่** ค้นพอร์ตอัตโนมัติ |
| `ARCGIS_MCP_TIMEOUT` | `600` | วินาทีที่รอ geoprocessing ที่ใช้เวลานาน |

ปกติไม่ต้องตั้งเลย — bridge จะเขียนไฟล์ลงทะเบียนไว้ที่
`%LOCALAPPDATA%\ArcGIS-MCP\instances\` ให้ฝั่ง MCP หาพอร์ตเจอเอง แม้พอร์ตจะเลื่อน

## โปรโตคอลภายใน (สำหรับผู้พัฒนา)

Bridge ใช้ newline-delimited JSON ผ่าน TCP:

```
request : {"id": 1, "command": "get_layers", "params": {"map_name": null}}\n
response: {"id": 1, "success": true, "data": {...}}\n
error   : {"id": 1, "success": false, "error": "...", "traceback": "..."}\n
```

### เพิ่มคำสั่งใหม่

1. เขียน handler ในโมดูลที่เหมาะสมใน [arcgis_pro_plugin/arcgis_mcp/](arcgis_pro_plugin/arcgis_mcp/)
   แล้วครอบด้วย `@command("ชื่อคำสั่ง", GROUP)` — ลงทะเบียนอัตโนมัติ
2. เพิ่ม 1 entry ใน [src/arcgis_pro_mcp/catalog.py](src/arcgis_pro_mcp/catalog.py)
   — MCP tool ถูก generate จากตรงนี้ พร้อม JSON schema และคำอธิบายพารามิเตอร์
3. ใน ArcGIS Pro รันเครื่องมือ **Reload MCP Handlers** เพื่อโหลดโค้ดใหม่
   โดยไม่ต้องปิด Pro
4. `python scripts/gen_tool_docs.py` เพื่ออัปเดตตารางใน README

### ทดสอบ

```powershell
python tests\test_catalog_matches_bridge.py   # catalog กับ handler ตรงกัน
python tests\test_end_to_end_mock.py          # protocol + error + image ครบวงจร
python tests\test_pump.py                     # queue/handoff ของ main-thread pump
```

ทั้งสองชุดรันได้โดยไม่ต้องมี ArcGIS Pro

## ข้อควรระวังด้านความปลอดภัย

- Bridge รับเฉพาะ **localhost** แต่โปรเซสใดก็ได้ในเครื่องเชื่อมต่อได้ และ
  `execute_arcpy_code` / `run_geoprocessing_tool` แก้ไขหรือลบข้อมูลได้จริง —
  เปิด server เฉพาะตอนใช้งาน บนเครื่องที่เชื่อถือได้เท่านั้น
- AI ทำงานกับ **โปรเจกต์จริงที่เปิดอยู่** — tool ที่ทำลายข้อมูลได้ถูกทำเครื่องหมาย ⚠️
  ไว้ในตารางด้านบน และ `update_features` / `delete_features` จะปฏิเสธถ้าไม่ใส่
  where clause เว้นแต่ยืนยันด้วย `allow_update_all` / `allow_delete_all`
- ควร save/backup โปรเจกต์ก่อนให้ AI แก้ไขข้อมูลจำนวนมาก

## แก้ปัญหาเบื้องต้น

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| "Cannot reach the ArcGIS Pro MCP bridge" | ยังไม่ได้เปิด Pro หรือ bridge ยังไม่ขึ้น — รัน `python -m arcgis_pro_mcp doctor` (บอกสถานะ auto-start ด้วย) |
| `OSError: CURRENT` แม้ติดตั้ง dispatcher แล้ว | dispatcher อาจถูกถอนไปแล้ว — เช็คด้วย `get_pump_status` |
| ติดตั้ง auto-start แล้วแต่ bridge ไม่ขึ้น | ดู `%LOCALAPPDATA%\ArcGIS-MCP\autostart.log` — บอกว่าตกด่านไหน |
| `OSError: CURRENT` / "dispatcher is not installed" | วาง `import mcp_bridge; mcp_bridge.start_pump()` ใน Python window ของ Pro |
| คำสั่งค้างนานผิดปกติแล้วขึ้นว่า bridge busy | มีคำสั่งก่อนหน้าค้างอยู่ — รีสตาร์ต ArcGIS Pro |
| "No active map" / "has no open view" | เปิดแท็บ map ใน Pro หรือเรียก `activate_map` ก่อน — คำสั่งกล้องและ export ต้องมี view ที่เปิดอยู่ |
| "Layer not found" | ใช้ชื่อตามที่ `get_layers` แสดง (layer ใน group ใช้ long name แบบ `Group\Layer`) |
| Tool ค้างนาน | geoprocessing ใช้เวลานาน — เพิ่ม `ARCGIS_MCP_TIMEOUT` |
| "Unknown command" | bridge เก่ากว่า MCP server — รัน **Reload MCP Handlers** ใน toolbox |
| แก้โค้ด bridge แล้วไม่มีผล | รัน **Reload MCP Handlers** (server ที่รันอยู่ไม่หลุด) |
| Response too large | ใส่ where clause, ลด `fields` หรือลด `limit` |

## โครงสร้าง repo

```
ArcGIS-MCP/
├── arcgis_pro_plugin/            # ทำงานภายใน ArcGIS Pro
│   ├── ArcGISMCP.pyt             # Toolbox: Start / Stop / Status / Reload
│   ├── arcgis_mcp_autostart.py   # hook ให้ bridge ขึ้นเองเมื่อเปิด Pro
│   ├── mcp_bridge.py             # socket server + instance discovery
│   └── arcgis_mcp/               # handler แยกตามหมวด (ลงทะเบียนอัตโนมัติ)
│       ├── registry.py           # @command decorator
│       ├── pump.py               # queue + loop บน main thread ของ Pro
│       ├── common.py             # helper ที่ใช้ร่วมกัน
│       └── h_*.py                # project, layers, data, schema, selection,
│                                 # geoprocessing, symbology, layout, view,
│                                 # raster, catalog, code
├── src/arcgis_pro_mcp/           # ทำงานนอก ArcGIS Pro
│   ├── catalog.py                # นิยาม tool ทั้งหมด (source of truth)
│   ├── server.py                 # FastMCP stdio server + prompts + resources
│   ├── connection.py             # TCP client + ค้นพอร์ตอัตโนมัติ
│   └── cli.py                    # doctor / tools / setup
├── scripts/gen_tool_docs.py      # อัปเดตตาราง tool ใน README
├── tests/                        # ตรวจ catalog และทดสอบครบวงจร (ไม่ต้องมี Pro)
├── install.ps1                   # ติดตั้ง + ลงทะเบียน client
├── .mcp.json
└── pyproject.toml
```
