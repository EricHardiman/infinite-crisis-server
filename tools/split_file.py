"""Split a big file into parts of at most 300 MB next to it (name.part1, name.part2, ...),
so the cloud session can copy it (400 MB limit per file). The parts are joined again there.

python tools\\split_file.py "C:\\path\\to\\video.mp4"
"""
import os
import sys

PART = 300 * 1024 * 1024


def main(path):
    n = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(PART)
            if not chunk:
                break
            n += 1
            out = f"{path}.part{n}"
            with open(out, "wb") as o:
                o.write(chunk)
            print(f"{out}: {len(chunk) / 1048576:.0f} MB")
    print(f"{n} parts. Tell Claude they are ready.")


if __name__ == "__main__":
    main(sys.argv[1])
