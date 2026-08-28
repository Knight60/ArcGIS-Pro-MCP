# -*- coding: utf-8 -*-
"""Map view, camera, bookmarks and screenshots."""

import base64
import os
import tempfile

import arcpy

from .common import (extent_dict, find_layer, get_map, live_view, project,
                     resolve_path, spatial_reference_from)
from .registry import command

GROUP = "view"


def _require_view(m):
    """Always the live view -- see common.live_view for why this matters."""
    return live_view(m, required=True)


@command("get_map_view", GROUP)
def get_map_view(params):
    """Current camera position: centre, scale, rotation and visible extent."""
    m = get_map(map_name=params.get("map_name"))
    view = _require_view(m)
    camera = view.camera
    data = {"map": m.name, "x": camera.X, "y": camera.Y, "scale": camera.scale,
            "heading": camera.heading}
    for attr in ("pitch", "roll", "z"):
        if hasattr(camera, attr):
            try:
                data[attr] = getattr(camera, attr)
            except Exception:
                pass
    try:
        data["extent"] = extent_dict(camera.getExtent())
    except Exception:
        pass
    return data


@command("set_map_view", GROUP)
def set_map_view(params):
    """Move the map view: set an extent, a centre point, a scale and/or rotation."""
    m = get_map(map_name=params.get("map_name"))
    view = _require_view(m)
    camera = view.camera
    applied = {}

    extent = params.get("extent")
    if extent:
        sr = spatial_reference_from(params.get("epsg")) if params.get("epsg") else None
        if isinstance(extent, dict):
            new_extent = arcpy.Extent(extent["xmin"], extent["ymin"],
                                      extent["xmax"], extent["ymax"])
        else:
            new_extent = arcpy.Extent(*[float(v) for v in extent[:4]])
        if sr is not None:
            new_extent = arcpy.Extent(new_extent.XMin, new_extent.YMin,
                                      new_extent.XMax, new_extent.YMax,
                                      spatial_reference=sr)
        camera.setExtent(new_extent)
        applied["extent"] = extent_dict(new_extent)

    if params.get("x") is not None and params.get("y") is not None:
        camera.X = float(params["x"])
        camera.Y = float(params["y"])
        applied["center"] = [camera.X, camera.Y]
    if params.get("scale") is not None:
        camera.scale = float(params["scale"])
        applied["scale"] = camera.scale
    if params.get("rotation") is not None:
        camera.heading = float(params["rotation"])
        applied["rotation"] = camera.heading
    if not applied:
        raise ValueError("Provide extent, x/y, scale and/or rotation")
    return {"map": m.name, "applied": applied}


@command("list_bookmarks", GROUP)
def list_bookmarks(params):
    """List spatial bookmarks defined on a map."""
    m = get_map(map_name=params.get("map_name"))
    bookmarks = []
    for bm in m.listBookmarks():
        entry = {"name": bm.name}
        try:
            entry["extent"] = extent_dict(bm.extent)
        except Exception:
            pass
        bookmarks.append(entry)
    return {"map": m.name, "bookmarks": bookmarks}


def _find_bookmark(m, name):
    for bm in m.listBookmarks():
        if bm.name == name:
            return bm
    raise ValueError(
        "Bookmark not found on map '{}': {}. Available: {}".format(
            m.name, name, ", ".join(b.name for b in m.listBookmarks()) or "(none)")
    )


@command("apply_bookmark", GROUP)
def apply_bookmark(params):
    """Zoom the map view to a bookmark."""
    m = get_map(map_name=params.get("map_name"))
    view = _require_view(m)
    bm = _find_bookmark(m, params["bookmark_name"])
    try:
        view.zoomToBookmark(bm)
    except AttributeError:
        view.camera.setExtent(bm.extent)
    return {"map": m.name, "applied_bookmark": bm.name}


@command("create_bookmark", GROUP)
def create_bookmark(params):
    """Save the current view (or a given extent) as a named bookmark."""
    m = get_map(map_name=params.get("map_name"))
    name = params["name"]
    view = _require_view(m)
    extent = params.get("extent")

    # Bookmarks capture wherever the view currently is, so a requested extent
    # is applied first and the user's view put back afterwards.
    previous = None
    if extent:
        previous = view.camera.getExtent()
        view.camera.setExtent(arcpy.Extent(
            extent["xmin"], extent["ymin"], extent["xmax"], extent["ymax"]))
    try:
        view.createBookmark(name, params.get("description"))
    finally:
        if previous is not None:
            view.camera.setExtent(previous)
    return {"map": m.name, "created_bookmark": name,
            "bookmarks": [b.name for b in m.listBookmarks()]}


@command("delete_bookmark", GROUP)
def delete_bookmark(params):
    """Delete a bookmark from a map."""
    m = get_map(map_name=params.get("map_name"))
    bm = _find_bookmark(m, params["bookmark_name"])
    m.removeBookmark(bm)
    return {"map": m.name, "deleted_bookmark": params["bookmark_name"]}


@command("export_map_view", GROUP)
def export_map_view(params):
    """Export the map view to PNG so the assistant can look at the map.

    Returns the image inline (base64) unless return_image is false.
    """
    proj = project()
    m = get_map(proj, params.get("map_name"))
    view = _require_view(m)
    width = int(params.get("width", 1200))
    height = int(params.get("height", 800))
    dpi = int(params.get("dpi", 96))
    return_image = params.get("return_image", True)

    output_path = params.get("output_path")
    temp_file = None
    if output_path:
        output_path = resolve_path(output_path, proj)
    else:
        handle, temp_file = tempfile.mkstemp(suffix=".png", prefix="arcgis_mcp_")
        os.close(handle)
        output_path = temp_file

    parent = os.path.dirname(output_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)

    if params.get("zoom_to_layer"):
        lyr = find_layer(m, params["zoom_to_layer"])
        view.camera.setExtent(arcpy.Describe(lyr).extent)

    view.exportToPNG(output_path, width, height, resolution=dpi)

    result = {"map": m.name, "width": width, "height": height,
              "scale": view.camera.scale}
    if not temp_file:
        result["exported"] = output_path
    if return_image:
        with open(output_path, "rb") as handle:
            result["image_base64"] = base64.b64encode(handle.read()).decode("ascii")
        result["image_format"] = "png"
    if temp_file:
        try:
            os.remove(temp_file)
        except OSError:
            pass
    return result
