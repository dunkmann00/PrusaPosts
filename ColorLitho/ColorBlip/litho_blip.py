#!/usr/local/bin/python3
# -*- coding: utf-8 -*-
from pathlib import Path
from math import sqrt
from collections import namedtuple
import argparse, re


BLIP_REMOVER_ENABLED = "; BLIP_REMOVER_ENABLED"
BLIP_REMOVER_DISABLED = "; BLIP_REMOVER_DISABLED"
LAYER_CHANGE_ID = ";LAYER_CHANGE"
RETRACT_BEFORE_TRAVEL_ID = "; retract_before_travel "
RETRACT_LENGTH_ID = "; retract_length "
RETRACT_SPEED_ID = "; retract_speed "
RETRACT_LIFT_ID = "; retract_lift "
TRAVEL_SPEED_ID = "; travel_speed "
TRAVEL_SPEED_Z_ID = "; travel_speed_z "
NOZZLE_DIAMETER_ID = "; nozzle_diameter"
WIPE_START = ";WIPE_START"
WIPE_END = ";WIPE_END"
M204_ID = "M204 P"
TYPE_ID = ";TYPE:"

g1_line = re.compile("^G1 (?:(?:X([0-9]*\.?[0-9]*) *)|(?:Y([0-9]*\.?[0-9]*) *)|(?:Z([0-9]*\.?[0-9]*) *)|(?:E(-?[0-9]*\.?[0-9]*) *)|(?:F([0-9]+) *))+$")
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
    for line in reversed(gcode_lines): # Go reversed because these things are found at the end
        if line.startswith(id):
            return line.split("=")[-1].strip()

def gcode_fmt(value, precision=3):
    return f"{value:.{precision}f}".strip("0") if value != 0 else "0.000"

def get_config_lines(args, gcode_lines):
    config_gcode_lines = []
    config_gcode_lines.append("; Post-Processed With BlipRemover")
    config_gcode_lines.append(f"; wipe_threshold = {args.wipe_threshold or get_value_for_id(RETRACT_BEFORE_TRAVEL_ID, gcode_lines).split(',')[0]}")
    config_gcode_lines.append("")
    return config_gcode_lines

def get_retraction_count(gcode_lines):
    retractions = 0
    for line in gcode_lines:
        g1 = parse_line(line)
        if g1 is not None:
            if g1.e is not None and g1.x is None and g1.y is None and g1.z is None:
                if g1.e < 0:
                    retractions += 1
    return retractions

def process_gcode(gcode_lines, wipe_threshold):
    travel_speed = int(get_value_for_id(TRAVEL_SPEED_ID, gcode_lines)) * 60     # convert to speed/min
    travel_speed_z = int(get_value_for_id(TRAVEL_SPEED_Z_ID, gcode_lines)) * 60 # convert to speed/min
    nozzle_diameter = float(get_value_for_id(NOZZLE_DIAMETER_ID, gcode_lines).split(",")[0])
    if wipe_threshold is None:
        wipe_threshold = float(get_value_for_id(RETRACT_BEFORE_TRAVEL_ID, gcode_lines).split(",")[0])

    retract_len = float(get_value_for_id(RETRACT_LENGTH_ID, gcode_lines).split(",")[0])
    retract_speed = int(get_value_for_id(RETRACT_SPEED_ID, gcode_lines).split(",")[0]) * 60 # convert to speed/min

    processed_gcode_lines = []

    i = 0

    current_m204_idx = None
    current_line_start_idx = None

    layer_change_idx = None

    current_type = None
    new_type = None

    blip_remover_enabled = False
    current_line_len = 0

    is_retracted = False
    remove_next_deretraction = False
    current_point = Point.undefined()
    prev_xy_point = Point.undefined()
    prev_line_end_point = Point.undefined()

    for (orig_idx, line) in enumerate(gcode_lines):
        processed_gcode_lines.append(line)

        if line == BLIP_REMOVER_ENABLED:
            blip_remover_enabled = True
        elif line == BLIP_REMOVER_DISABLED:
            blip_remover_enabled = False
            current_point = Point.undefined()
            prev_xy_point = Point.undefined()
        elif line == LAYER_CHANGE_ID:
            layer_change_idx = i
        elif blip_remover_enabled:
            g1 = parse_line(line)
            if g1 is not None:
                new_point = current_point.updated_with_g1_move(g1)

                if g1.e is not None and current_point.is_xy_equal(new_point):
                    is_retracted = g1.e < 0
                    if not is_retracted and remove_next_deretraction:
                        processed_gcode_lines[i] = "; BLIP_REMOVER REMOVE RETRACTION END"
                        remove_next_deretraction = False

                if current_point.is_fully_defined:
                    if g1.e is None and not current_point.is_xy_equal(new_point): # Travel move found
                        if current_line_len > 0 and current_line_len < nozzle_diameter:
                            gcode_len = len(processed_gcode_lines)
                            del processed_gcode_lines[current_line_start_idx:current_m204_idx]
                            i -= gcode_len - len(processed_gcode_lines)
                            global lines_removed
                            lines_removed += 1
                        else:
                            prev_line_end_point = current_point
                            current_line_start_idx = current_m204_idx
                            current_type = new_type
                        current_line_len = 0

                        if layer_change_idx > current_line_start_idx:
                            prev_line_end_point = Point.undefined()

                        if prev_line_end_point.is_fully_defined:
                            if new_point.xy_dist(prev_line_end_point) > wipe_threshold and not is_retracted:
                                gcode_len = len(processed_gcode_lines)
                                processed_gcode_lines.insert(i, f"G1 E-{gcode_fmt(retract_len)} F{retract_speed}")
                                processed_gcode_lines.append(f"G1 E{gcode_fmt(retract_len)} F{retract_speed}")

                                processed_gcode_lines.insert(i, "; BLIP_REMOVER RETRACTION START")
                                processed_gcode_lines.append("; BLIP_REMOVER RETRACTION END")

                                i += len(processed_gcode_lines) - gcode_len
                            elif new_point.xy_dist(prev_line_end_point) <= wipe_threshold and is_retracted:
                                processed_gcode_lines[i-1] = "; BLIP_REMOVER REMOVE RETRACTION START"
                                remove_next_deretraction = True

                            if current_type != new_type:
                                processed_gcode_lines.append(new_type)
                                i += 1

                    elif g1.e is not None and g1.e > 0 and not current_point.is_xy_equal(new_point): # Extrusion
                        current_line_len += current_point.xy_dist(new_point)

                if not new_point.is_xy_equal(current_point):
                    prev_xy_point = current_point
                current_point = new_point
            elif line.startswith(M204_ID):
                current_m204_idx = i
                if current_line_start_idx is None or layer_change_idx > current_line_start_idx:
                    prev_line_end_point = current_point
                    current_line_start_idx = current_m204_idx
                    if current_type != new_type:
                        processed_gcode_lines.append(new_type)
                        i += 1
            elif line.startswith(TYPE_ID):
                new_type = line
        i+=1

    return processed_gcode_lines

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file_path", help="The path to the gcode file to process.")
    parser.add_argument("--wipe-threshold", help="When the upcoming travel distance is greater than this, the wipe and hop is added. The default is the 'Minimum travel after retraction' slicer setting.", type=float)
    parser.add_argument("--output-file-path", help="The path to save the processed output to. If not given, the original file is overwrtiten.")
    args = parser.parse_args()
    gcode_path = Path(args.file_path)
    print("Loading G-code...")
    gcode_lines = get_gcode_lines(gcode_path)
    print(f"{get_retraction_count(gcode_lines)} retractions performed before.")
    print("Removing short lines...")
    gcode_lines = process_gcode(gcode_lines, args.wipe_threshold)
    print("Complete!")
    print(f"{lines_removed} short lines removed.")
    print(f"{get_retraction_count(gcode_lines)} retractions performed after.")
    gcode_lines += get_config_lines(args, gcode_lines)
    output_file_path = Path(args.output_file_path) if args.output_file_path is not None else gcode_path
    store_gcode_lines(gcode_lines, output_file_path)
    print("G-code Saved!")

if __name__ == '__main__':
    main()
