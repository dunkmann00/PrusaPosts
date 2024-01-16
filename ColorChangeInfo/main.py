from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.text import Text
import argparse, os, re

EXTRUDER_COLOURS = "; extruder_colour"

toolhead_change_re = re.compile("^T([0-9]+)$", flags=re.MULTILINE)

def load_gcode(file_path):
    return file_path.read_text()

def save_gcode(gcode, file_path):
    file_path.write_text(gcode)

def wipe_tower_enabled(gcode):
    wipe_tower_start_idx = gcode.rfind(WIPE_TOWER_ENABLED)
    if wipe_tower_start_idx == -1:
        return False

    wipe_tower_end_idx = gcode.find("\n", wipe_tower_start_idx)
    if wipe_tower_end_idx == -1:
        return False

    wipe_tower_setting_line = gcode[wipe_tower_start_idx:wipe_tower_end_idx]
    return int(wipe_tower_setting_line.split("=")[-1].strip()) == 1

def get_extruder_colours(gcode):
    extruder_color_start_idx = gcode.rfind(EXTRUDER_COLOURS)
    if extruder_color_start_idx == -1:
        return None

    extruder_color_end_idx = gcode.find("\n", extruder_color_start_idx)
    if extruder_color_end_idx == -1:
        return None

    extruder_colour_line = gcode[extruder_color_start_idx:extruder_color_end_idx]
    extruder_colour_line_value = extruder_colour_line.split("=")[-1].strip()
    extruder_colours = extruder_colour_line_value.split(";")
    return extruder_colours

def get_progress_at(gcode, progress_idx_start):
    progress_idx_end = gcode.find("\n", progress_idx_start)
    if progress_idx_end == -1:
        return None

    progress_line = gcode[progress_idx_start:progress_idx_end]
    return int(progress_line.split("R")[-1])

def get_total_time(gcode):
    progress_idx_start = gcode.find("M73 P")
    if progress_idx_start == -1:
        return None

    return get_progress_at(gcode, progress_idx_start)

def get_toolchange_info(gcode, m):
    extruder = int(m.group(1))

    idx = m.start()
    progress_idx_start = gcode.rfind("M73 P", 0, idx)
    if progress_idx_start == -1:
        return (None, extruder)

    progress = get_progress_at(gcode, progress_idx_start)

    return (progress, extruder)

def format_time(total_mins):
    hrs = total_mins // 60
    mins = total_mins % 60
    time_str = f"{mins} min{'s' if mins > 1 else ''}"
    if hrs > 0:
        time_str = f"{hrs} hr{'s' if hrs > 1 else ''} {time_str}"
    return time_str



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file_path", help="The path to the gcode file to process.")
    args = parser.parse_args()
    gcode_path = Path(args.file_path)
    console = Console()

    console.print("Loading G-code...")
    gcode = load_gcode(gcode_path)

    total_time = get_total_time(gcode)

    console.print("Finding toolchanges...")
    toolchange_info = [get_toolchange_info(gcode, m) for m in toolhead_change_re.finditer(gcode)]

    extruder_colours = get_extruder_colours(gcode)

    console.print(f"\nTotal Print Time: {format_time(total_time)}\n")

    table = Table(title="Toolchanges", row_styles=["on grey30", ""])
    table.add_column("Toolchange #")
    table.add_column("Extruder #")
    table.add_column("Color", justify="center")
    table.add_column("Time Remaining at Change")
    table.add_column("Duration")

    for (i, (time, extruder)) in enumerate(toolchange_info):
        remaining_time = time if i > 0 else total_time
        next_remaing_time = toolchange_info[i+1][0] if i < len(toolchange_info) - 1 else 0
        table.add_row(f"{i if i > 0 else '-'}", f"{extruder+1}", Text("███", style=extruder_colours[extruder]), format_time(remaining_time), format_time(remaining_time-next_remaing_time))

    console.print(table)

if __name__ == "__main__":
    main()
