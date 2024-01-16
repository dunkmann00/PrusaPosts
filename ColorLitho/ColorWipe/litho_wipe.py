#!/usr/local/bin/python3
# -*- coding: utf-8 -*-
from pathlib import Path
from math import sqrt
from collections import namedtuple
import argparse, re


CUSTOM_HOP_ENABLED = "; CUSTOM_HOP_ENABLED"
CUSTOM_HOP_DISABLED = "; CUSTOM_HOP_DISABLED"
RETRACT_BEFORE_TRAVEL_ID = "; retract_before_travel "
RETRACT_LIFT_ID = "; retract_lift "
TRAVEL_SPEED_ID = "; travel_speed "
TRAVEL_SPEED_Z_ID = "; travel_speed_z "
NOZZLE_DIAMETER_ID = "; nozzle_diameter"
WIPE_START = ";WIPE_START"
WIPE_END = ";WIPE_END"

g1_line = re.compile("^G1 (?:(?:X([0-9]*\.?[0-9]*) *)|(?:Y([0-9]*\.?[0-9]*) *)|(?:Z([0-9]*\.?[0-9]*) *)|(?:E(-?[0-9]*\.?[0-9]*) *)|(?:F([0-9]+) *))+$")
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
    config_gcode_lines.append("; Post-Processed With ColorLithoHop")
    config_gcode_lines.append(f"; lift_z = {args.lift_z}")
    config_gcode_lines.append(f"; wipe_multiplier = {args.wipe_multiplier}")
    config_gcode_lines.append(f"; wipe_threshold = {args.wipe_threshold or get_value_for_id(RETRACT_BEFORE_TRAVEL_ID, gcode_lines).split(',')[0]}")
    config_gcode_lines.append("")
    return config_gcode_lines

def process_gcode(gcode_lines, retract_lift, wipe_multiplier, wipe_threshold):
    travel_speed = int(get_value_for_id(TRAVEL_SPEED_ID, gcode_lines)) * 60     # convert to speed/min
    travel_speed_z = int(get_value_for_id(TRAVEL_SPEED_Z_ID, gcode_lines)) * 60 # convert to speed/min
    nozzle_diameter = float(get_value_for_id(NOZZLE_DIAMETER_ID, gcode_lines).split(",")[0])
    wipe_dist = nozzle_diameter * wipe_multiplier
    if wipe_threshold is None:
        wipe_threshold = float(get_value_for_id(RETRACT_BEFORE_TRAVEL_ID, gcode_lines).split(",")[0])

    processed_gcode_lines = []

    i = 0

    custom_hop_enabled = False
    z_change_idx = None
    current_point = Point.undefined()
    prev_xy_point = Point.undefined()
    for line in gcode_lines:
        processed_gcode_lines.append(line)

        if line == CUSTOM_HOP_ENABLED:
            custom_hop_enabled = True
        elif line == CUSTOM_HOP_DISABLED:
            custom_hop_enabled = False
            z_change_idx = None
            current_point = Point.undefined()
            prev_xy_point = Point.undefined()
        elif custom_hop_enabled:
            g1 = parse_line(line)
            if g1 is not None:
                new_point = current_point.updated_with_g1_move(g1)

                if current_point.is_fully_defined:
                    if g1.e is None and current_point.xy_dist(new_point) > wipe_threshold: # Travel move over threshold found
                        if z_change_idx is not None: # Now that we found a travel, remove the z height move. This is needed to handle layer changes
                            processed_gcode_lines[z_change_idx] = ""
                            z_change_idx = None
                        gcode_len = len(processed_gcode_lines)

                        wipe_point = current_point.wipe_point(prev_xy_point, wipe_dist)
                        processed_gcode_lines[-1] = WIPE_START
                        processed_gcode_lines.append(f"G1 X{gcode_fmt(wipe_point.x)} Y{gcode_fmt(wipe_point.y)} F{travel_speed}")
                        processed_gcode_lines.append(WIPE_END)

                        processed_gcode_lines.append(f"G1 Z{gcode_fmt(current_point.z + retract_lift)} F{travel_speed_z}")

                        processed_gcode_lines.append(line)
                        processed_gcode_lines.append(f"G1 Z{gcode_fmt(new_point.z)} F{travel_speed_z}")
                        i += len(processed_gcode_lines) - gcode_len
                    elif g1.z is not None:
                        z_change_idx = i
                if not new_point.is_xy_equal(current_point):
                    prev_xy_point = current_point
                current_point = new_point

        i+=1

    return processed_gcode_lines

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file_path", help="The path to the gcode file to process.")
    parser.add_argument("--lift-z", help="The amount to raise z during retraction hops.", type=float, default=0.2)
    parser.add_argument("--wipe-multiplier", help="The distance to wipe the nozzle is computed by taking the nozzle diameter and multiplying it be this amount.", type=float, default=2)
    parser.add_argument("--wipe-threshold", help="When the upcoming travel distance is greater than this, the wipe and hop is added. The default is the 'Minimum travel after retraction' slicer setting.", type=float)
    parser.add_argument("--output-file-path", help="The path to save the processed output to. If not given, the original file is overwrtiten.")
    args = parser.parse_args()
    gcode_path = Path(args.file_path)
    print("Loading G-code...")
    gcode_lines = get_gcode_lines(gcode_path)
    print("Adding custom hops...")
    gcode_lines = process_gcode(gcode_lines, args.lift_z, args.wipe_multiplier, args.wipe_threshold)
    print("Complete!")
    gcode_lines += get_config_lines(args, gcode_lines)
    output_file_path = Path(args.output_file_path) if args.output_file_path is not None else gcode_path
    store_gcode_lines(gcode_lines, output_file_path)
    print("G-code Saved!")

if __name__ == '__main__':
    main()
