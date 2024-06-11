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

TRAVEL_EXTRUSION_MULT_ENABLED = "; TRAVEL_EXTRUSION_MULT_ENABLED"
TRAVEL_EXTRUSION_MULT_DISABLED = "; TRAVEL_EXTRUSION_MULT_DISABLED"
COLOR_CHANGE_ID = "M600"
LAYER_CHANGE_ID = ";LAYER_CHANGE"
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
    def wipe_point(self, prev_point, distance):
        point_dist = prev_point.xy_dist(self)
        p = 1.0 + (distance / point_dist)
        dx = (self.x - prev_point.x) * p
        dy = (self.y - prev_point.y) * p
        return prev_point._replace(x=prev_point.x+dx, y=prev_point.y+dy, z=self.z)
    def is_xy_equal(self, point):
        return self.x == point.x and self.y == point.y

class GCodeConfig:
    def __init__(self, gcode_lines, **kwargs):
        # self.travel_speed = int(get_value_for_id(TRAVEL_SPEED_ID, gcode_lines)) * 60     # convert to speed/min
        # self.travel_speed_z = int(get_value_for_id(TRAVEL_SPEED_Z_ID, gcode_lines)) * 60 # convert to speed/min
        # self.nozzle_diameter = float(get_value_for_id(NOZZLE_DIAMETER_ID, gcode_lines).split(",")[0])

        # self.wipe_threshold = float(get_value_for_id((FILAMENT_RETRACT_BEFORE_TRAVEL_ID, RETRACT_BEFORE_TRAVEL_ID), gcode_lines).split(",")[0])

        self.retract_len = float(get_value_for_id((FILAMENT_RETRACT_LENGTH_ID, RETRACT_LENGTH_ID), gcode_lines))
        # self.retract_speed = int(get_value_for_id((FILAMENT_RETRACT_SPEED_ID, RETRACT_SPEED_ID), gcode_lines).split(",")[0]) * 60 # convert to speed/min
        # self.retract_layer_change = int(get_value_for_id((FILAMENT_RETRACT_LAYER_CHANGE, RETRACT_LAYER_CHANGE), gcode_lines).split(",")[0]) == 1

        # self.wipe = int(get_value_for_id((FILAMENT_WIPE_ID, WIPE_ID), gcode_lines).split(",")[0]) == 1
        # self.z_hop = float(get_value_for_id((FILAMENT_Z_HOP_ID, Z_HOP_ID), gcode_lines).split(",")[0])
        self.deretract_speed = int(get_value_for_id((FILAMENT_DERETRACT_SPEED_ID, DERETRACT_SPEED_ID), gcode_lines)) * 60 # convert to speed/min
        self.arc_fitting = get_value_for_id(ARC_FITTING, gcode_lines) == "emit_center"

        for name, value in kwargs.items():
            setattr(self, name, value)

class GCode:
    def __init__(self, gcode_lines, config):
        self.config = config

        # if self.config.wipe:
        #     raise RuntimeError("ColorBlip does not currently support 'Wipe while retracting'.")
        # if self.config.z_hop > 0:
        #     raise RuntimeError("ColorBlip does not currently support 'Lift Height' (aka Z-Hop).")
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
        travel_extrusion_mult_enabled = True

        pre_end_idx = 0
        for i, line in enumerate(gcode_lines):
            if line == TRAVEL_EXTRUSION_MULT_ENABLED:
                travel_extrusion_mult_enabled = True
            elif line == TRAVEL_EXTRUSION_MULT_DISABLED:
                travel_extrusion_mult_enabled = False
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
            if line == TRAVEL_EXTRUSION_MULT_ENABLED:
                travel_extrusion_mult_enabled = True
            elif line == TRAVEL_EXTRUSION_MULT_DISABLED:
                travel_extrusion_mult_enabled = False
            elif line == LAYER_CHANGE_ID:
                if layer_start_idx is not None:
                    layer = Layer(gcode_lines[layer_start_idx:i], self.config, current_point, travel_extrusion_mult_enabled)
                    current_point = layer.end_point
                    layers.append(layer)
                layer_start_idx = i
        # Handle the last layer
        layer = Layer(gcode_lines[layer_start_idx:post_start_idx], self.config, current_point, travel_extrusion_mult_enabled)
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

    # @property
    # def has_layer_color_change(self):
    #     return COLOR_CHANGE_ID in self._pre_print

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
        for i, line in enumerate(gcode_lines):
            g1 = parse_line(line)
            if g1 is not None:
                new_point = current_point.updated_with_g1_move(g1)
                if g1.e is None and not current_point.is_xy_equal(new_point): # Travel move found
                    pre_end_idx = i
                    break
                current_point = new_point

        lines = []
        line_start_idx = pre_end_idx
        line_start_point = start_point
        # current_type = None
        for i, line in enumerate(gcode_lines[pre_end_idx:], start=pre_end_idx):
            g1 = parse_line(line)
            if g1 is not None:
                new_point = current_point.updated_with_g1_move(g1)
                if g1.e is None and not current_point.is_xy_equal(new_point): # Travel move found
                    line = Line(gcode_lines[line_start_idx:i], self.config, line_start_point, current_point, enabled)
                    lines.append(line)
                    line_start_idx = i
                    line_start_point = new_point
                current_point = new_point
            # elif line.startswith(TYPE_ID):
            #     current_type = line
        line = Line(gcode_lines[line_start_idx:], self.config, line_start_point, current_point, enabled)
        lines.append(line)
        return gcode_lines[:pre_end_idx], lines, current_point

class Line:
    def __init__(self, gcode_lines, config, start_point, end_point, enabled):
        self.config = config

        self.start_point = start_point
        self.end_point = end_point
        # self.type = type
        self.enabled = enabled
        self.lines = self.process_gcode_lines(gcode_lines)

    def gcode_lines(self):
        return self.lines

    # @property
    # def line_length(self):
    #     current_point = self.start_point
    #     length = 0
    #     for line in self.lines:
    #         g1 = parse_line(line)
    #         if g1 is not None:
    #             new_point = current_point.updated_with_g1_move(g1)
    #             length += current_point.xy_dist(new_point)
    #     return length

    def process_gcode_lines(self, gcode_lines):
        if not self.enabled or not self.has_deretraction(gcode_lines):
            return gcode_lines

        lines = []
        current_extrusion_remaining = self.config.travel_multiplier_distance
        current_point = self.start_point
        for i, line in enumerate(gcode_lines):
            if current_extrusion_remaining > 0:
                g1 = parse_line(line)
                if g1 is not None:
                    new_point = current_point.updated_with_g1_move(g1)
                    if g1.e is not None and g1.e > 0 and not current_point.is_xy_equal(new_point):
                        extrusion_distance = current_point.xy_dist(new_point)
                        if current_extrusion_remaining >= extrusion_distance:
                            lines.append(f"G1 X{gcode_fmt(new_point.x)} Y{gcode_fmt(new_point.y)} E{gcode_fmt(g1.e * self.config.travel_extrusion_multiplier, precision=5)} ; TEM Updated ({self.config.travel_extrusion_multiplier}x)")
                        else:
                            waypoint = current_point.waypoint(new_point, current_extrusion_remaining)
                            waypoint_proportion = current_extrusion_remaining / extrusion_distance
                            lines.append(f"G1 X{gcode_fmt(waypoint.x)} Y{gcode_fmt(waypoint.y)} E{gcode_fmt(g1.e * waypoint_proportion * self.config.travel_extrusion_multiplier, precision=5)} ; TEM Updated ({self.config.travel_extrusion_multiplier}x)")
                            lines.append(f"G1 X{gcode_fmt(new_point.x)} Y{gcode_fmt(new_point.y)} E{gcode_fmt(g1.e * (1.0 - waypoint_proportion), precision=5)} ; TEM Updated")
                        current_extrusion_remaining -= extrusion_distance
                        current_point = new_point
                        continue
                    else:
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

    # def add_deretraction(self, position=None):
    #     if self.config.retract_len > 0:
    #         position = 1 if position is None else position
    #         self.lines.insert(position, f"G1 E{gcode_fmt(self.config.retract_len)} F{self.config.retract_speed}")

    # def add_retraction(self, position=None):
    #     if self.config.retract_len > 0:
    #         position = len(self.lines) if position is None else position
    #         self.lines.insert(position, f"G1 E-{gcode_fmt(self.config.retract_len)} F{self.config.retract_speed}")
    #         position += 1
    #         self.lines.insert(position, f"G1 F{self.config.travel_speed}")

    # def add_start_feedrate(self):
    #     g1 = parse_line(self.lines[0])
    #     if g1.f is None:
    #         self.lines[0] += f" F{self.config.travel_speed}"

    # @staticmethod
    # def type_removed(gcode_lines):
    #     return [line for line in gcode_lines if not line.startswith(TYPE_ID)]

    # @staticmethod
    # def retractions_removed(gcode_lines):
    #     for i in range(-1, max(-5, len(gcode_lines) * -1), -1):
    #         line = gcode_lines[i]
    #         g1 = parse_line(line)
    #         if g1 is not None and g1.x is None and g1.y is None and g1.z is None and g1.e is not None:
    #             gcode_lines = gcode_lines[:i]
    #             break
    #
    #     for i in range(0, min(5, len(gcode_lines))):
    #         line = gcode_lines[i]
    #         g1 = parse_line(line)
    #         if g1 is not None and g1.x is None and g1.y is None and g1.z is None and g1.e is not None:
    #             del gcode_lines[i]
    #             break
    #     return gcode_lines


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
    config_gcode_lines.append("; Post-Processed With TravelExtrusionMultiplier (aka TEM)")
    for name, value in sorted(vars(config).items()):
        if isinstance(value, bool):
            value = int(value)
        config_gcode_lines.append(f"; {name} = {value}")
    config_gcode_lines.append("")
    return config_gcode_lines

# def get_retraction_count(gcode_lines):
#     retractions = 0
#     for line in gcode_lines:
#         g1 = parse_line(line)
#         if g1 is not None:
#             if g1.e is not None and g1.x is None and g1.y is None and g1.z is None:
#                 if g1.e < 0:
#                     retractions += 1
#     return retractions

# def process_gcode(gcode_lines, **kwargs):
#     gcode = GCode(gcode_lines, **kwargs)
#     return gcode.gcode_lines()

def main():
    parser = argparse.ArgumentParser(description="Apply an extrusion multiplier for a small amount of the extrusion after a travel move occurs.")
    parser.add_argument("file_path", help="The path to the gcode file to process.")
    # parser.add_argument("--wipe-threshold", help="When the upcoming travel distance is greater than this, the wipe and hop is added. The default is the 'Minimum travel after retraction' slicer setting.", type=float)
    parser.add_argument("-m", "--travel-extrusion-multiplier", help="The extrusion multiplier to apply to the initial extrusion after a travel move.", type=float, default=1.1)
    parser.add_argument("-d", "--travel-multiplier-distance", help="The distance to apply the extrusion multiplier after a travel move.", type=float, default=1.0)
    parser.add_argument("--output-file-path", help="The path to save the processed output to. If not given, the original file is overwrtiten.")
    args = parser.parse_args()
    gcode_path = Path(args.file_path)
    print("Loading G-code...")
    gcode_lines = get_gcode_lines(gcode_path)
    # print(f"{get_retraction_count(gcode_lines)} retractions performed before.")
    # print("Removing short lines...")
    print("Adding extrusion multiplier after travels...")
    config_args = vars(args).copy()
    config_args.pop("file_path")
    config_args.pop("output_file_path", None)

    gcode_config = GCodeConfig(gcode_lines, **config_args)
    gcode = GCode(gcode_lines, gcode_config)
    gcode_lines = gcode.gcode_lines()
    print("Complete!")
    # print(f"{lines_removed} short lines removed.")
    # print(f"{get_retraction_count(gcode_lines)} retractions performed after.")
    gcode_lines += get_config_lines(gcode_config)
    output_file_path = Path(args.output_file_path) if args.output_file_path is not None else gcode_path
    store_gcode_lines(gcode_lines, output_file_path)
    print("G-code Saved!")

if __name__ == '__main__':
    main()
