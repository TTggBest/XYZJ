"""Build the uploadable V2 skill; does not install, select defaults or call APIs."""
import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def build(destination):
    root = Path(__file__).resolve().parents[1] / 'backend/zhiju/scheduling_v2_rules'
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                archive.write(path, path.relative_to(root).as_posix())
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    print(build(parser.parse_args().output))
