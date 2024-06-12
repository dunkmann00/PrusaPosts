#!/usr/local/bin/python3
# -*- coding: utf-8 -*-
from pathlib import Path
from math import sqrt
from collections import namedtuple
import argparse, re

# G-Code
#   |
#   |--> Pre-Print   Print   Post-Print
#                      |
#                      |-->  Pre-Print   Layers
#                                          |
#                                          |--> Lines

GAP_CLOSER_ENABLED = "; GAP_CLOSER_ENABLED"
GAP_CLOSER_DISABLED = "; GAP_CLOSER_DISABLED"
COLOR_CHANGE_ID = "M600"
LAYER_CHANGE_ID = ";LAYER_CHANGE"
AFTER_LAYER_CHANGE_ID = ";AFTER_LAYER_CHANGE"
RETRACT_BEFORE_TRAVEL_ID = "; retract_before_travel "
FILAMENT_RETRACT_BEFORE_TRAVEL_ID = "; filament_retract_before_travel "
RETRACT_LENGTH_ID = "; retract_length "
FILAMENT_RETRACT_LENGTH_ID = "; filament_retract_length "
RETRACT_LAYER_CHANGE = "; retract_layer_change "
FILAMENT_RETRACT_LAYER_CHANGE = "; filament_retract_layer_change "
RETRACT_SPEED_ID = "; retract_speed "
FILAMENT_RETRACT_SPEED_ID = "; filament_retract_speed "
DERETRACT_SPEED_ID = "; deretract_speed"
FILAMENT_DERETRACT_SPEED_ID = "; filament_deretract_speed"
RETRACT_LIFT_ID = "; retract_lift "
TRAVEL_SPEED_ID = "; travel_speed "
TRAVEL_SPEED_Z_ID = "; travel_speed_z "
NOZZLE_DIAMETER_ID = "; nozzle_diameter"
WIPE_ID = "; wipe "
FILAMENT_WIPE_ID = "; filament_wipe "
WIPE_START = ";WIPE_START"
WIPE_END = ";WIPE_END"
M204_ID = "M204 P"
START_PRINTING_OBJECT_ID = "; printing object"
STOP_PRINTING_OBJECT_ID = "; stop printing object"
TYPE_ID = ";TYPE:"
Z_HOP_ID = "; retract_lift "
FILAMENT_Z_HOP_ID = "; filament_retract_lift "
ARC_FITTING = "; arc_fitting"
M107 = "M107"

PRUSA_CONFIG_ID = "; prusaslicer_config = "

g1_line = re.compile("^G1 (?:(?:X([0-9]*\\.?[0-9]*) *)|(?:Y([0-9]*\\.?[0-9]*) *)|(?:Z([0-9]*\\.?[0-9]*) *)|(?:E(-?[0-9]*\\.?[0-9]*) *)|(?:F([0-9]+) *))+$")
G1 = namedtuple("G1", ["x", "y", "z", "e", "f"])

lines_removed = 0

class Point(namedtuple("Point", ["x", "y", "z"])):
    __slots__ = ()
    @classmethod
    def undefined(cls):
        return cls(None, None, None)
    @property
    def is_fully_defined(self):
        return self.x is not None and self.y is not None and self.z is not None
    def xy_dist(self, point):
        return sqrt((point.x - self.x)**2 + (point.y - self.y)**2)
    def updated_with_g1_move(self, g1):
        update_point = {}
        if g1.x is not None:
            update_point["x"] = g1.x
        if g1.y is not None:
            update_point["y"] = g1.y
        if g1.z is not None:
            update_point["z"] = g1.z
        return self._replace(**update_point)
    def waypoint(self, point, distance):
        point_dist = self.xy_dist(point)
        if distance >= point_dist:
            return point
        p = distance / point_dist
        dx = (point.x - self.x) * p
        dy = (point.y - self.y) * p
        return self._replace(x=self.x+dx, y=self.y+dy)
    def back_up_point(self, next_point, distance):
        point_dist = next_point.xy_dist(self)
        p = distance / point_dist
        dx = (next_point.x - self.x) * p
        dy = (next_point.y - self.y) * p
        return next_point._replace(x=self.x-dx, y=self.y-dy, z=self.z)
    def is_xy_equal(self, point):
        return self.x == point.x and self.y == point.y

class GCodeConfig:
    def __init__(self, gcode_lines, **kwargs):
        self.retract_len = float(get_value_for_id((FILAMENT_RETRACT_LENGTH_ID, RETRACT_LENGTH_ID), gcode_lines))
        self.deretract_speed = int(get_value_for_id((FILAMENT_DERETRACT_SPEED_ID, DERETRACT_SPEED_ID), gcode_lines)) * 60 # convert to speed/min
        self.arc_fitting = get_value_for_id(ARC_FITTING, gcode_lines) == "emit_center"

        for name, value in kwargs.items():
            setattr(self, name, value)

class GCode:
    def __init__(self, gcode_lines, config):
        self.config = config

        if self.config.arc_fitting:
            raise RuntimeError("Arc Fitting is not supported.")

        pre, post, layers = self.process_gcode_lines(gcode_lines)
        self._pre_print = pre
        self._post_print = post
        self.layers = layers

    @property
    def pre_print_gcode_lines(self):
        return self._pre_print

    @property
    def print(self):
        gcode_lines = []
        for layer in self.layers:
            gcode_lines += layer.gcode_lines()
        return gcode_lines

    @property
    def post_print_gcode_lines(self):
        return self._post_print

    def gcode_lines(self):
        return self._pre_print + self.print + self._post_print

    def process_gcode_lines(self, gcode_lines):
        current_point = Point.undefined()
        gap_closer_enabled = True

        pre_end_idx = 0
        for i, line in enumerate(gcode_lines):
            if line == GAP_CLOSER_ENABLED:
                gap_closer_enabled = True
            elif line == GAP_CLOSER_DISABLED:
                gap_closer_enabled = False
            elif line == LAYER_CHANGE_ID:
                pre_end_idx = i
                break
            else:
                g1 = parse_line(line)
                if g1 is not None:
                    current_point = current_point.updated_with_g1_move(g1)

        post_start_idx = len(gcode_lines)
        for i, line in enumerate(reversed(gcode_lines)):
            i_rev = len(gcode_lines) - i - 1
            if line.startswith(M107):
                post_start_idx = i_rev + 1
                break

        layers = []
        layer_start_idx = None
        for i, line in enumerate(gcode_lines[pre_end_idx:post_start_idx], start=pre_end_idx):
            if line == GAP_CLOSER_ENABLED:
                gap_closer_enabled = True
            elif line == GAP_CLOSER_DISABLED:
                gap_closer_enabled = False
            elif line == LAYER_CHANGE_ID:
                if layer_start_idx is not None:
                    layer = Layer(gcode_lines[layer_start_idx:i], self.config, current_point, gap_closer_enabled)
                    current_point = layer.end_point
                    layers.append(layer)
                layer_start_idx = i
        # Handle the last layer
        layer = Layer(gcode_lines[layer_start_idx:post_start_idx], self.config, current_point, gap_closer_enabled)
        current_point = layer.end_point
        layers.append(layer)

        return gcode_lines[:pre_end_idx], gcode_lines[post_start_idx:], layers

class Layer:
    def __init__(self, gcode_lines, config, start_point, enabled):
        self.config = config
        pre, lines, end_point = self.process_gcode_lines(gcode_lines, start_point, enabled)
        self._pre_print = pre
        self.lines = lines
        self.start_point = start_point
        self.end_point = end_point
        self.enabled = enabled

    @property
    def pre_print_gcode_lines(self):
        return self._pre_print

    @property
    def print(self):
        gcode_lines = []
        for line in self.lines:
            gcode_lines += line.gcode_lines()
        return gcode_lines

    def gcode_lines(self):
        return self._pre_print + self.print

    def process_gcode_lines(self, gcode_lines, start_point, enabled):
        pre_end_idx = 0
        current_point = start_point
        is_after_layer_change = False
        for i, line in enumerate(gcode_lines):
            if line == AFTER_LAYER_CHANGE_ID:
                is_after_layer_change = True
            else:
                g1 = parse_line(line)
                if g1 is not None:
                    new_point = current_point.updated_with_g1_move(g1)
                    if is_after_layer_change and g1.e is None and (g1.x or g1.y or g1.z) is not None:
                        pre_end_idx = i
                        start_point = new_point
                        break
                    current_point = new_point

        lines = []
        line_start_idx = pre_end_idx
        line_start_point = start_point
        extrusion_end_point = start_point
        wipe_start_idx = None
        wipe_end_idx = None
        for i, line in enumerate(gcode_lines[pre_end_idx:], start=pre_end_idx):
            g1 = parse_line(line)
            if g1 is not None:
                new_point = current_point.updated_with_g1_move(g1)
                if g1.e is not None and g1.e > 0:
                    extrusion_end_point = new_point # Tells us where extruding ends (needed when there is also a wipe)
                if g1.e is None and not current_point.is_xy_equal(new_point): # Travel move found
                    wipe_indices = (wipe_start_idx, wipe_end_idx) if wipe_start_idx is not None else None
                    line = Line(gcode_lines[line_start_idx:i], self.config, line_start_point, current_point, extrusion_end_point, wipe_indices, enabled)
                    lines.append(line)
                    line_start_idx = i
                    line_start_point = new_point
                    wipe_start_idx = None
                    wipe_end_idx = None
                current_point = new_point
            elif line == WIPE_START:
                wipe_start_idx = i - line_start_idx
            elif line == WIPE_END:
                wipe_end_idx = i - line_start_idx

        wipe_indices = (wipe_start_idx, wipe_end_idx) if wipe_start_idx is not None else None
        line = Line(gcode_lines[line_start_idx:], self.config, line_start_point, current_point, extrusion_end_point, wipe_indices, enabled)
        lines.append(line)
        return gcode_lines[:pre_end_idx], lines, current_point

class Line:
    def __init__(self, gcode_lines, config, start_point, end_point, extrusion_end_point, wipe_indices, enabled):
        self._has_seam = None

        self.config = config

        self.start_point = start_point
        self.end_point = end_point
        self.extrusion_end_point = extrusion_end_point
        self.wipe_indices = wipe_indices
        self.enabled = enabled
        self.lines = self.process_gcode_lines(gcode_lines)

    @property
    def has_seam(self):
        if self._has_seam is not None:
            return self._has_seam
        self._has_seam = self.start_point.xy_dist(self.extrusion_end_point) < 0.5
        return self._has_seam

    def gcode_lines(self):
        return self.lines

    def process_gcode_lines(self, gcode_lines):
        if not self.enabled or not self.has_deretraction(gcode_lines):
            return gcode_lines

        lines = []
        current_point = self.start_point
        is_first_extrude = True
        for i, line in enumerate(gcode_lines):
            if is_first_extrude:
                g1 = parse_line(line)
                if g1 is not None:
                    new_point = current_point.updated_with_g1_move(g1)
                    if g1.e is not None and g1.e > 0 and not current_point.is_xy_equal(new_point):
                        distance = current_point.xy_dist(new_point)
                        e_rate = g1.e / distance
                        if self.has_seam:
                            back_up_lines = self.get_back_up_lines(gcode_lines, e_rate)
                            lines[0] = back_up_lines[0]
                            lines += back_up_lines[1:]
                            lines.append(line)
                        else:
                            back_up_point = current_point.back_up_point(new_point, self.config.back_up_distance)
                            start_g1 = parse_line(gcode_lines[0])
                            start_line = f"G1 X{gcode_fmt(back_up_point.x)} Y{gcode_fmt(back_up_point.y)}"
                            if start_g1.z is not None:
                                start_line += f" Z{gcode_fmt(start_g1.z)}"
                            if start_g1.f is not None:
                                start_line += f" F{int(start_g1.f)}"
                            start_line += " ; GapCloser"
                            lines[0] = start_line
                            lines.append(f"G1 X{gcode_fmt(new_point.x)} Y{gcode_fmt(new_point.y)} E{gcode_fmt(e_rate * (distance + self.config.back_up_distance), precision=5)} ; GapCloser")
                        is_first_extrude = False
                        continue
                    current_point = new_point
            lines.append(line)
        return lines

    def has_deretraction(self, gcode_lines):
        for i in range(0, min(5, len(gcode_lines))):
            line = gcode_lines[i]
            g1 = parse_line(line)
            if g1 is not None and g1.x is None and g1.y is None and g1.z is None and g1.e is not None and g1.f is not None:
                if g1.e == self.config.retract_len and g1.f == self.config.deretract_speed:
                    return True
        return False

    def get_back_up_lines(self, gcode_lines, initial_e_rate):
        lines = []
        current_point = self.start_point
        extrusion_remaining = self.config.back_up_distance
        if self.wipe_indices is not None:
            gcode_lines = gcode_lines[:self.wipe_indices[0]]
        while extrusion_remaining > 0:
            prev_e = initial_e_rate * self.start_point.xy_dist(self.extrusion_end_point)
            for i, line in enumerate(reversed(gcode_lines)):
                i = len(gcode_lines) - i - 1
                if extrusion_remaining <= 0:
                    break
                g1 = parse_line(line)
                if g1 is not None:
                    new_point = current_point.updated_with_g1_move(g1)
                    if not current_point.is_xy_equal(new_point):
                        distance = current_point.xy_dist(new_point)
                        new_e = g1.e
                        if new_e is None and new_point != self.start_point:
                            continue # At the end of extrudes there are speed changes, ignore them
                        if extrusion_remaining > distance:
                            lines.append(f"G1 X{gcode_fmt(current_point.x)} Y{gcode_fmt(current_point.y)} E{gcode_fmt(prev_e, precision=5)} ; GapCloser (Seam)")
                        else:
                            waypoint = current_point.waypoint(new_point, extrusion_remaining)
                            waypoint_proportion = extrusion_remaining / distance
                            lines.append(f"G1 X{gcode_fmt(current_point.x)} Y{gcode_fmt(current_point.y)} E{gcode_fmt(prev_e * waypoint_proportion, precision=5)} ; GapCloser (Seam)")

                            start_g1 = parse_line(gcode_lines[0])
                            start_line = f"G1 X{gcode_fmt(waypoint.x)} Y{gcode_fmt(waypoint.y)}"
                            if start_g1.z is not None:
                                start_line += f" Z{gcode_fmt(start_g1.z)}"
                            if start_g1.f is not None:
                                start_line += f" F{int(start_g1.f)}"
                            start_line += " ; GapCloser (Seam)"
                            lines.append(start_line)
                        extrusion_remaining -= distance
                        prev_e = new_e
                        current_point = new_point
        lines = list(reversed(lines))
        return lines

def parse_line(gcode_line):
    result = g1_line.match(gcode_line)
    if result:
        return G1._make((float(group) if group is not None else None for group in result.groups()))
    return None

def get_gcode_lines(gcode_path):
    with Path(gcode_path).open() as f:
        gcode = f.read()
        return gcode.split("\n")

def store_gcode_lines(gcode_lines, gcode_path):
    gcode_text = "\n".join(gcode_lines)
    gcode_path.write_text(gcode_text)

def get_value_for_id(id, gcode_lines):
    if isinstance(id, str):
        id = [id]
    for gcode_id in id:
        for line in reversed(gcode_lines): # Go reversed because these things are found at the end
            if line.startswith(gcode_id):
                return line.split("=")[-1].strip()
            elif line.startswith(PRUSA_CONFIG_ID):
                if line.split("=")[-1].strip() == "begin":
                    break

def gcode_fmt(value, precision=3):
    return f"{value:.{precision}f}".strip("0") if value != 0 else "0.000"

def get_config_lines(config):
    config_gcode_lines = []
    config_gcode_lines.append("; Post-Processed With GapCloser")
    for name, value in sorted(vars(config).items()):
        if isinstance(value, bool):
            value = int(value)
        config_gcode_lines.append(f"; {name} = {value}")
    config_gcode_lines.append("")
    return config_gcode_lines

def main():
    parser = argparse.ArgumentParser(prog="GapCloser", description="Close up small gaps/holes that can be found at the start of extrusions after travel moves with deretractions.")
    parser.add_argument("file_path", help="The path to the gcode file to process.")
    parser.add_argument("-d", "--back-up-distance", help="The distance to back up the extrusion by after a travel move with a deretraction.", type=float, default=1.0)
    parser.add_argument("--output-file-path", help="The path to save the processed output to. If not given, the original file is overwrtiten.")
    args = parser.parse_args()
    gcode_path = Path(args.file_path)
    print("Loading G-code...")
    gcode_lines = get_gcode_lines(gcode_path)

    print("Fixing gaps...")
    config_args = vars(args).copy()
    config_args.pop("file_path")
    config_args.pop("output_file_path", None)

    gcode_config = GCodeConfig(gcode_lines, **config_args)
    gcode = GCode(gcode_lines, gcode_config)
    gcode_lines = gcode.gcode_lines()
    print("Complete!")

    gcode_lines += get_config_lines(gcode_config)
    output_file_path = Path(args.output_file_path) if args.output_file_path is not None else gcode_path
    store_gcode_lines(gcode_lines, output_file_path)
    print("G-code Saved!")

if __name__ == '__main__':
    main()
