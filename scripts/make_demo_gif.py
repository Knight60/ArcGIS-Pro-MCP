"""Build the animated GIF in the README, by actually driving ArcGIS Pro.

Every frame is rendered by the add-in's own export_map_view after running the
command the caption describes. Nothing is mocked up and nothing is a screen
recording: what the GIF shows is what the tool did, which is the only kind of
demo worth putting at the top of a README.

    python scripts/make_demo_gif.py

Needs ArcGIS Pro open with a polygon layer to play with. It changes symbology,
selection, labelling and the view -- and never saves the project, so closing
Pro without saving puts everything back.
"""
from __future__ import annotations

import argparse
import io
import pathlib
import sys
import time

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from arcgis_pro_mcp.connection import get_connection  # noqa: E402

WIDTH, HEIGHT = 760, 620          # map area
CAPTION_HEIGHT = 96
BACKGROUND = (255, 255, 255)
CAPTION_BACKGROUND = (24, 27, 32)
PROMPT_COLOUR = (255, 255, 255)
REPLY_COLOUR = (126, 231, 135)
HOLD_MS = 2600                    # how long each finished frame is held

# Given outright rather than by ramp name: no ramp shipped with ArcGIS Pro is
# called pastel, and the caption promises pastel.
PASTEL_RED_TO_GREEN = [
    [245, 169, 169, 255], [247, 196, 165, 255], [249, 224, 162, 255],
    [237, 239, 168, 255], [205, 233, 168, 255], [169, 221, 169, 255],
    [143, 209, 158, 255],
]
FADE_MS = 60


def font(size, bold=False):
    for name in (("segoeuib.ttf", "seguisb.ttf") if bold else ("segoeui.ttf",)):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


PROMPT_FONT = font(23, bold=True)
REPLY_FONT = font(18)


class Demo:
    def __init__(self, layer, field):
        self.connection = get_connection()
        self.layer = layer
        self.field = field
        self.frames: list[Image.Image] = []

    # --- talking to ArcGIS Pro ------------------------------------------------

    def run(self, command, **parameters):
        parameters.setdefault("layer_name", self.layer) if command not in (
            "export_map_view", "set_map_view", "clear_selection") else None
        reply = self.connection.send_command(command, parameters)
        if not reply.get("success"):
            raise RuntimeError(f"{command}: {reply.get('error')}")
        return reply["data"]

    def map_image(self):
        data = self.run("export_map_view", width=WIDTH, height=HEIGHT,
                        dpi=96, return_image=True)
        import base64
        exported = Image.open(io.BytesIO(base64.b64decode(data["image_base64"])))
        # The export carries an alpha channel: everything outside the data is
        # transparent. Converting straight to RGB paints that black, which is
        # how the first attempt came out.
        if exported.mode in ("RGBA", "LA"):
            canvas = Image.new("RGB", exported.size, BACKGROUND)
            canvas.paste(exported, mask=exported.split()[-1])
            return canvas
        return exported.convert("RGB")

    # --- drawing --------------------------------------------------------------

    def compose(self, prompt, reply):
        map_image = self.map_image().resize((WIDTH, HEIGHT), Image.LANCZOS)
        frame = Image.new("RGB", (WIDTH, HEIGHT + CAPTION_HEIGHT), BACKGROUND)
        frame.paste(map_image, (0, CAPTION_HEIGHT))

        draw = ImageDraw.Draw(frame)
        draw.rectangle([0, 0, WIDTH, CAPTION_HEIGHT], fill=CAPTION_BACKGROUND)
        draw.text((24, 22), f"›  {prompt}", font=PROMPT_FONT, fill=PROMPT_COLOUR)
        if reply:
            draw.text((24, 58), reply, font=REPLY_FONT, fill=REPLY_COLOUR)
        return frame

    def step(self, prompt, reply, action):
        print(f"  {prompt}")
        action()
        time.sleep(0.4)                      # let the map finish drawing
        self.frames.append(self.compose(prompt, reply))


def build(layer, field, output):
    demo = Demo(layer, field)

    # A clean starting point, so the first frame is not whatever was left over.
    demo.run("clear_selection")
    demo.run("set_layer_labeling", enabled=False)
    demo.run("set_layer_renderer", renderer_type="simple",
             color=[236, 240, 241, 255], outline_color=[150, 160, 170, 255],
             outline_width=0.4)
    demo.run("zoom_to_layer", expand_factor=0.05)

    demo.step("Show me the provinces", "77 features", lambda: None)

    demo.step(
        "Colour them by area, pastel red through green",
        "graduated on AreaKm2, 7 classes",
        lambda: demo.run("set_layer_renderer", renderer_type="graduated_colors",
                         field=field, break_count=7,
                         classification_method="NaturalBreaks",
                         class_colors=PASTEL_RED_TO_GREEN,
                         outline_color=[150, 160, 170, 255], outline_width=0.4))

    demo.step(
        "Which ones are bigger than 15,000 km²?",
        "7 selected",
        lambda: demo.run("select_features", where=f"{field} > 15000"))

    demo.step(
        "Zoom to those",
        "zoomed to the selection",
        lambda: demo.run("zoom_to_selection"))

    demo.step(
        "Label them",
        "labels on",
        lambda: (demo.run("set_layer_labeling", enabled=True,
                          expression="$feature.PROV_NAME", font_size=11,
                          bold=True, halo_size=2),
                 demo.run("clear_selection")))

    # Labels drawn for the whole country overlap into noise, so the closing
    # frame goes back to the map that made the point.
    demo.run("set_layer_labeling", enabled=False)
    demo.run("zoom_to_layer", expand_factor=0.05)
    demo.frames.append(demo.compose("Anything ArcGIS Pro can do, in a sentence.",
                                    "112 tools · ~9 ms each · github.com/Knight60/ArcGIS-Pro-MCP"))

    output.parent.mkdir(parents=True, exist_ok=True)
    demo.frames[0].save(
        output, save_all=True, append_images=demo.frames[1:],
        duration=[HOLD_MS] * (len(demo.frames) - 1) + [HOLD_MS + 1500],
        loop=0, optimize=True)
    print(f"\n  {output}  ({output.stat().st_size:,} bytes, {len(demo.frames)} frames)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", default="Province")
    parser.add_argument("--field", default="AreaKm2")
    parser.add_argument("--output", type=pathlib.Path,
                        default=pathlib.Path(__file__).resolve().parent.parent
                        / "docs" / "images" / "demo.gif")
    arguments = parser.parse_args()
    build(arguments.layer, arguments.field, arguments.output)
