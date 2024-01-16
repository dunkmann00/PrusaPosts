#!/usr/local/bin/python3
# -*- coding: utf-8 -*-
from pathlib import Path
from math import sqrt
from collections import namedtuple
import argparse, re


LITHO_REORDER_ENABLED = "; LITHO_REORDER_ENABLED"
LITHO_REORDER_DISABLED = "; LITHO_REORDER_DISABLED"
LAYER_CHANGE_ID = ";LAYER_CHANGE"
PROGRESS_ID = "M73 P"
MANUAL_COLOR_CHANGE_ID = "M600 ; "
RETRACT_BEFORE_TRAVEL_ID = "; retract_before_travel "
RETRACT_LIFT_ID = "; retract_lift "
TRAVEL_SPEED_ID = "; travel_speed "
TRAVEL_SPEED_Z_ID = "; travel_speed_z "
NOZZLE_DIAMETER_ID = "; nozzle_diameter"
WIPE_START = ";WIPE_START"
WIPE_END = ";WIPE_END"
START_PRINTING_OBJECT_ID = "; printing object"
STOP_PRINTING_OBJECT_ID = "; stop printing object"

g1_line = re.compile("^G1 (?:(?:X([0-9]*\.?[0-9]*) *)|(?:Y([0-9]*\.?[0-9]*) *)|(?:Z([0-9]*\.?[0-9]*) *)|(?:E(-?[0-9]*\.?[0-9]*) *)|(?:F([0-9]+) *))+$")
toolhead_change_line = re.compile("^T([0-9]+)$")
progress_line = re.compile("^M73 P([0-9]+) R([0-9]+)$")
G1 = namedtuple("G1", ["x", "y", "z", "e", "f"])

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

class PrintComponent:
    def __init__(self, start_idx=None, end_idx=None, layer=None, toolhead=None, extrusion_length=None):
        self.start_idx = start_idx
        self.end_idx = end_idx
        self.layer = layer
        self.toolhead = toolhead
        self.extrusion_length = extrusion_length

    def __str__(self):
        return f"PrintComponent(start_idx={self.start_idx}, end_idx={self.end_idx}, layer={self.layer}, toolhead={self.toolhead}, extrusion_length={self.extrusion_length})"

    def __repr__(self):
        return str(self)

def parse_line(gcode_line):
    result = g1_line.match(gcode_line)
    if result is not None:
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
    for line in reversed(gcode_lines): # Go reversed because these things are found at the end
        if line.startswith(id):
            return line.split("=")[-1].strip()

def gcode_fmt(value, precision=3):
    return f"{value:.{precision}f}".strip("0") if value != 0 else "0.000"

def get_config_lines():
    gcode_lines = []
    gcode_lines.append("; Post-Processed With ColorLithoReorder")
    gcode_lines.append("")
    return gcode_lines

def get_print_components(gcode_lines):
    print_components = [[]]

    litho_reorder_enabled = False
    current_layer = -1
    current_toolhead = None
    start_print_component_i = None
    for i, line in enumerate(gcode_lines):
        if line == LAYER_CHANGE_ID:
            current_layer += 1
        if line == LITHO_REORDER_ENABLED:
            litho_reorder_enabled = True
        elif line == LITHO_REORDER_DISABLED:
            litho_reorder_enabled = False
        else:
            toolhead_change = toolhead_change_line.match(line)
            if toolhead_change is not None:
                current_toolhead = int(toolhead_change.group(1))
            elif litho_reorder_enabled:
                if line.startswith(START_PRINTING_OBJECT_ID):
                    start_print_component_i = i
                elif line.startswith(STOP_PRINTING_OBJECT_ID):
                    new_component = PrintComponent(
                        start_idx=start_print_component_i,
                        end_idx=i+1,
                        layer=current_layer,
                        toolhead = current_toolhead
                    )
                    if len(print_components[-1]) > 0 and print_components[-1][-1].layer != current_layer:
                        print_components.append([])
                    print_components[-1].append(new_component)
                    start_print_component_i = None
    return print_components

def get_extrusion_length(gcode_lines, start, end):
    extrusion_length = 0
    current_point = Point(None, None, 0) # z doesn't matter for this
    for i in range(start, end):
        line = gcode_lines[i]
        g1 = parse_line(line)
        if g1 is not None:
            new_point = current_point.updated_with_g1_move(g1)

            if current_point.is_fully_defined and g1.e is not None and g1.e > 0 and (g1.x is not None or g1.y is not None or g1.z is not None):
                extrusion_length += current_point.xy_dist(new_point)
            current_point = new_point
    return extrusion_length

def process_gcode_toolhead_order(gcode_lines):
    print_components = get_print_components(gcode_lines)
    for layer in print_components:
        for print_component in layer:
            print_component.extrusion_length = get_extrusion_length(gcode_lines, print_component.start_idx, print_component.end_idx)
    sorted_print_components = [sorted(layer, key=lambda x: x.extrusion_length) for layer in print_components]
    processed_gcode_lines = []
    i = 0
    for layer, sorted_layer in zip(print_components, sorted_print_components):
        for print_component, sorted_print_component in zip(layer, sorted_layer):
            non_object_lines = gcode_lines[i:print_component.start_idx]
            for i in range(len(non_object_lines)-1, -1, -1):
                line = non_object_lines[i]
                toolhead_change = toolhead_change_line.match(line)
                if toolhead_change is not None:
                    non_object_lines[i] = f"T{sorted_print_component.toolhead}"
                    if i > 0 and non_object_lines[i-1].startswith(MANUAL_COLOR_CHANGE_ID):
                        non_object_lines[i-1] = f"M600 ; change to filament for extruder {sorted_print_component.toolhead + 1}"
                    break
            processed_gcode_lines += non_object_lines
            processed_gcode_lines += gcode_lines[sorted_print_component.start_idx:sorted_print_component.end_idx]
            i = print_component.end_idx
    processed_gcode_lines += gcode_lines[i:]
    return processed_gcode_lines

def fix_progress(processed_gcode_lines, gcode_lines):
    progress_lines = (line for line in gcode_lines if line.startswith(PROGRESS_ID))

    for i in range(len(processed_gcode_lines)):
        line = processed_gcode_lines[i]
        if line.startswith(PROGRESS_ID):
            processed_gcode_lines[i] = next(progress_lines)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file_path", help="The path to the gcode file to process.")
    parser.add_argument("--output-file-path", help="The path to save the processed output to. If not given, the original file is overwrtiten.")
    args = parser.parse_args()
    gcode_path = Path(args.file_path)
    print("Loading G-code...")
    gcode_lines = get_gcode_lines(gcode_path)
    print("Updating toolhead order to optimize print...")
    processed_gcode_lines = process_gcode_toolhead_order(gcode_lines)
    print("Updating progress info...")
    fix_progress(processed_gcode_lines, gcode_lines)
    print("Complete!")
    processed_gcode_lines += get_config_lines()
    output_file_path = Path(args.output_file_path) if args.output_file_path is not None else gcode_path
    store_gcode_lines(processed_gcode_lines, output_file_path)
    print("G-code Saved!")

if __name__ == '__main__':
    main()
