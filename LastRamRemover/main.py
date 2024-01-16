#!/usr/local/bin/python3
# -*- coding: utf-8 -*-
from pathlib import Path
import argparse

TOOLCHANGE_START = "; CP TOOLCHANGE START\n"
TOOLCHANGE_END = "; CP TOOLCHANGE END\n;------------------"
TOTAL_TOOLCHANGES = "; total toolchanges"
WIPE_END = ";WIPE_END\n"
STOP_PRINTING = "; stop printing object"


def load_gcode(file_path):
    return file_path.read_text()

def save_gcode(gcode, file_path):
    file_path.write_text(gcode)

def get_toolchange_count(gcode, idx):
    tchange_count_start = idx + len(TOOLCHANGE_START)
    tchange_count_end = gcode.find("\n", tchange_count_start)
    if tchange_count_end == -1:
        return None
    toolchange_line = gcode[tchange_count_start:tchange_count_end]
    return int(toolchange_line.split("#")[-1])

def get_total_toolchange_count(gcode):
    total_toolchange_start = gcode.rfind(TOTAL_TOOLCHANGES) # Doing rfind since we know its near the end so should be faster
    if total_toolchange_start == -1:
        return None

    total_toolchange_end = gcode.find("\n", total_toolchange_start)
    if total_toolchange_end == -1:
        return None

    total_toolchange_line = gcode[total_toolchange_start:total_toolchange_end]
    return int(total_toolchange_line.split("=")[-1].strip())

def find_ram_start(gcode, idx):
    end = gcode.rfind(WIPE_END, 0, idx)
    if end != -1:
        return end + len(WIPE_END)

    end = gcode.rfind(STOP_PRINTING, 0, idx)
    if end != -1:
        line_end = gcode.find("\n", end)
        return line_end

    return None

def find_ram_end(gcode, idx):
    tchange_end_idx = gcode.find(TOOLCHANGE_END, idx)
    if tchange_end_idx == -1:
        return None
    return tchange_end_idx + len(TOOLCHANGE_END) + 1

def find_last_ram(gcode):
    toolchange_start_idx = gcode.rfind(TOOLCHANGE_START)
    if toolchange_start_idx == -1:
        return None

    total_toolchanges = get_total_toolchange_count(gcode)

    if total_toolchanges is None:
        return None

    if not (get_toolchange_count(gcode, toolchange_start_idx) > total_toolchanges):
        # We don't have the right ram/toolchange, so abort
        return None

    ram_start_idx = find_ram_start(gcode, toolchange_start_idx)
    if ram_start_idx is None:
        return None

    ram_end_idx = find_ram_end(gcode, toolchange_start_idx)
    if ram_end_idx is None:
        return None

    return (ram_start_idx, ram_end_idx)

def remove_chars_from_gcode(gcode, begin, end):
    return gcode[:begin] + gcode[end:]

def get_config_lines():
    gcode_lines = []
    gcode_lines.append("; Post-Processed With LastRamRemover")
    gcode_lines.append("")
    return gcode_lines

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file_path", help="The path to the gcode file to process.")
    args = parser.parse_args()
    gcode_path = Path(args.file_path)
    print("Loading G-code...")
    gcode = load_gcode(gcode_path)
    print("Finding last ram...")
    ram_range = find_last_ram(gcode)
    if ram_range is None:
        print("Could not find the correct last ram.")
        return
    print("Removing last ram and tower wipe...")
    gcode = remove_chars_from_gcode(gcode, ram_range[0], ram_range[1])
    print("Successfully removed last ram and tower wipe!")
    save_gcode(gcode, gcode_path)
    print("G-code Saved!")


if __name__ == "__main__":
    main()
