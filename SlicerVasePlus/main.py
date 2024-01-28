#!/Users/georgewaters/.local/share/virtualenvs/SlicerVasePlus-LHgjP8U2/bin/python
# -*- coding: utf-8 -*-
from pathlib import Path
from math import sqrt
from scipy import spatial
import numpy as np
import argparse, re


LAYER_CHANGE = ";LAYER_CHANGE"

g1_line = re.compile("^G1 (?:Z([0-9]*\.?[0-9]*) )?(?:X([0-9]*\.?[0-9]*)) (?:Y([0-9]*\.?[0-9]*)) (?:E([0-9]*\.?[0-9]*))$")

def parse_point(gcode_line, z=None):
    result = g1_line.match(gcode_line)
    if result:
        point_z = result.group(1) or z
        if point_z is not None:
            return (result, (float(result.group(2)), float(result.group(3)), float(point_z)))
    return (None, None)

def interpolate_pts(point1, point2, distance=-1):
    if distance == -1 or xy_dist(point1, point2) <= distance:
        return []

    interpolated_pt_list = []
    x = point1[0] + (point2[0] - point1[0]) / 2
    y = point1[1] + (point2[1] - point1[1]) / 2

    interpolated_pt = (x, y)

    interpolated_pt_list.extend(interpolate_pts(point1, interpolated_pt, distance=distance))
    interpolated_pt_list.append(interpolated_pt)
    interpolated_pt_list.extend(interpolate_pts(interpolated_pt, point2, distance=distance))

    return interpolated_pt_list

def parse_all_points(gcode_lines, interpolate_distance=-1):
    points = []
    for line in gcode_lines:
        result, point = parse_point(line)
        if point is not None:
            xy_point = (point[0], point[1])
            if len(points) > 0:
                interpolated_pts = interpolate_pts(points[-1], xy_point, distance=interpolate_distance)
                points.extend(interpolated_pts)
            points.append(xy_point)

    if len(points) > 2:
        interpolated_pts = interpolate_pts(points[-1], points[0], distance=interpolate_distance)
        points.extend(interpolated_pts)

    return points

def get_gcode_lines(gcode_path):
    with Path(gcode_path).open() as f:
        gcode = f.read()
        return gcode.split("\n")

def store_gcode_lines(gcode_lines, gcode_path):
    gcode_text = "\n".join(gcode_lines)
    gcode_path.write_text(gcode_text)

def find_nearest_idx(array, value):
    return (np.abs(array - value)).argmin()

def xy_dist(point1, point2):
    return sqrt((point1[0] - point2[0])**2 + (point1[1] - point2[1])**2)

def layer_length(xy_pts):
    if len(xy_pts) > 1:
        return sum([xy_dist(xy_pts[i], xy_pts[i-1]) if i > 0 else 0 for i in range(len(xy_pts))])
    return 0

def gcode_fmt(value, precision=3):
    return f"{value:.{precision}f}".strip("0") if value != 0 else "0.000"

def get_config_lines(args):
    gcode_lines = []
    gcode_lines.append("; Post-Processed With SlicerVasePlus")
    gcode_lines.append(f"; reversed = {args.reversed}")
    gcode_lines.append(f"; combined = {args.combined}")
    gcode_lines.append(f"; range = {args.range}")
    gcode_lines.append(f"; interpolate_distance = {args.interpolate_distance}")
    gcode_lines.append(f"; smoothness_ratio = {args.smoothness_ratio}")
    gcode_lines.append("")
    return gcode_lines

def adjust_layer(vase_gcode_lines, layer_start_idx, layer_end_idx, prev_layer_array, prev_layer_kd_tree, is_reversed=False, interpolate_distance=-1, smoothness_ratio=1.0):
    points = parse_all_points(vase_gcode_lines[layer_start_idx:layer_end_idx], interpolate_distance=interpolate_distance)
    if len(points) == 0:
        print("No points in layer")
        return None

    prev_pt = prev_layer_array[-1] if prev_layer_array is not None and len(prev_layer_array) > 0 else None
    prev_adjusted_pt = prev_pt

    current_length = 0
    if prev_pt is not None:
        total_length = layer_length([prev_pt] + points)
    else:
        total_length = layer_length([points[-1]] + points)

    for i in range(layer_start_idx, layer_end_idx):
        line = vase_gcode_lines[i]

        try:
            result, point = parse_point(line)
        except Exception as e:
            print(f"Error from line #: {i}")
            print(f"Line: {line}")
            raise
        if point is not None and point[2] is not None:
            extrusion = float(result.group(4))
            extrusion_rate = None
            if prev_pt is not None:
                length = xy_dist(prev_pt, point)
                extrusion_rate = extrusion/length
                current_length += length

            progress = max(min(current_length / (total_length * smoothness_ratio), 1.0), 0.0)
            if is_reversed:
                progress = 1.0 - progress

            if prev_layer_array is not None and len(prev_layer_array) > 0:
                nearest_xy_prev = prev_layer_array[prev_layer_kd_tree.query((point[0], point[1]))[1]]

                adjusted_x = nearest_xy_prev[0] + (point[0] - nearest_xy_prev[0]) * progress
                adjusted_y = nearest_xy_prev[1] + (point[1] - nearest_xy_prev[1]) * progress

                if prev_adjusted_pt is not None and extrusion_rate is not None:
                    adjusted_e = xy_dist(prev_adjusted_pt, (adjusted_x, adjusted_y)) * extrusion_rate
            else:
                adjusted_x = point[0]
                adjusted_y = point[1]
                adjusted_e = extrusion

            x_text = gcode_fmt(adjusted_x)
            y_text = gcode_fmt(adjusted_y)
            z_text = gcode_fmt(point[2])
            e_text = gcode_fmt(adjusted_e, precision=5)

            new_line = f"G1 Z{z_text} X{x_text} Y{y_text} E{e_text}"
            vase_gcode_lines[i] = new_line

            prev_pt = point
            prev_adjusted_pt = (adjusted_x, adjusted_y)

    return points

def smooth_vase_gcode(vase_gcode_path, is_reversed=False, smooth_layer_range=None, interpolate_distance=-1, smoothness_ratio=1.0):
    vase_gcode_lines = get_gcode_lines(vase_gcode_path)
    vase_gcode_layers = []

    if smooth_layer_range is not None:
        smooth_layer_range = (smooth_layer_range[0]-1, smooth_layer_range[1])

    is_layer_change = False
    layer_idx = -1
    layer_start_idx = 0
    layer_end_idx = 0
    for i in range(len(vase_gcode_lines)):
        line = vase_gcode_lines[i]
        if is_layer_change:
            is_layer_change = False
            if smooth_layer_range is None:
                if layer_idx >= 0:
                    vase_gcode_layers.append((layer_start_idx, layer_end_idx))
            else:
                if layer_idx >= smooth_layer_range[0] and layer_idx <= smooth_layer_range[1]:
                    vase_gcode_layers.append((layer_start_idx, layer_end_idx))
            layer_idx += 1
            layer_start_idx = i
        elif line == LAYER_CHANGE:
            is_layer_change = True
            layer_end_idx = i

    prev_layer_array = None
    prev_layer_kd_tree = None
    if is_reversed:
        vase_gcode_layers = reversed(vase_gcode_layers)
    for layer in vase_gcode_layers:
        layer_start_idx, layer_end_idx = layer
        prev_layer_xy_pts = adjust_layer(vase_gcode_lines, layer_start_idx, layer_end_idx, prev_layer_array, prev_layer_kd_tree, is_reversed=is_reversed, interpolate_distance=interpolate_distance, smoothness_ratio=smoothness_ratio)
        if prev_layer_xy_pts is not None:
            prev_layer_array = np.array(prev_layer_xy_pts)
            prev_layer_kd_tree = spatial.KDTree(prev_layer_array)

    return vase_gcode_lines

def combined_smooth(vase_gcode_lines1, vase_gcode_lines2):
    vase_gcode_lines3 = vase_gcode_lines1.copy()
    for i in range(len(vase_gcode_lines1)):
        lineA = vase_gcode_lines1[i]
        lineB = vase_gcode_lines2[i]
        try:
            resultA, pointA = parse_point(lineA)
        except Exception as e:
            print(f"Error from line #: {i}")
            print(f"Line A: {lineA}")
            raise

        try:
            resultB, pointB = parse_point(lineB)
        except Exception as e:
            print(f"Error from line #: {i}")
            print(f"Line B: {lineB}")
            raise

        if pointA is not None and pointA[2] is not None and pointB is not None and pointB[2] is not None:
            adjusted_x = pointA[0] + (pointB[0] - pointA[0]) * 0.5
            adjusted_y = pointA[1] + (pointB[1] - pointA[1]) * 0.5

            x_text = f"{adjusted_x:.3f}".strip("0")
            y_text = f"{adjusted_y:.3f}".strip("0")
            z_text = f"{pointA[2]:.3f}".strip("0")

            new_line = f"G1 Z{z_text} X{x_text} Y{y_text} E{resultA.group(4)}"
            vase_gcode_lines3[i] = new_line

    return vase_gcode_lines3

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("vase_gcode", help="The path to the vase gcode file to process.")
    parser.add_argument("--reversed", help="Smooth the object from the top down, rather than bottom up.", action="store_true")
    parser.add_argument("--combined", help="Smooth the object from both the top down and bottom up and combine the results.", action="store_true")
    parser.add_argument("--range", help="Only smooth layers within this range.")
    parser.add_argument("--interpolate-distance", help="Interpolate inbetween points on a layer. This value is the desired distance between each interpolated point in mm.", type=float, default=-1)
    parser.add_argument("--smoothness-ratio", help="Smooth layer lines over a proportion of their length. If smoothness_ratio is 1, smooth over the entire length, 0.5, half the length, etc...", type=float, default=1.0)
    parser.add_argument("--output-file-path", help="The path to save the processed output to. If not given, the original file is overwritten.")
    args = parser.parse_args()
    vase_gcode_path = Path(args.vase_gcode)
    smooth_layer_range = None
    if args.range is not None:
        smooth_layer_range = args.range.split("...")
        smooth_layer_range = (int(smooth_layer_range[0]), int(smooth_layer_range[1]))
    if args.combined:
        smoothed_vase_gcode_lines1 = smooth_vase_gcode(vase_gcode_path, is_reversed=False, smooth_layer_range=smooth_layer_range, interpolate_distance=args.interpolate_distance, smoothness_ratio=args.smoothness_ratio)
        smoothed_vase_gcode_lines2 = smooth_vase_gcode(vase_gcode_path, is_reversed=True, smooth_layer_range=smooth_layer_range, interpolate_distance=args.interpolate_distance, smoothness_ratio=args.smoothness_ratio)
        smoothed_vase_gcode_lines = combined_smooth(smoothed_vase_gcode_lines1, smoothed_vase_gcode_lines2)
    else:
        smoothed_vase_gcode_lines = smooth_vase_gcode(vase_gcode_path, is_reversed=args.reversed, smooth_layer_range=smooth_layer_range, interpolate_distance=args.interpolate_distance, smoothness_ratio=args.smoothness_ratio)
    smoothed_vase_gcode_lines += get_config_lines(args)
    output_file_path = Path(args.output_file_path) if args.output_file_path is not None else vase_gcode_path
    store_gcode_lines(smoothed_vase_gcode_lines, output_file_path)

if __name__ == '__main__':
    main()
