import argparse
import json

from .seed import DatasetError, install


def main():
    parser = argparse.ArgumentParser(description='Initialize the autumn 2026 contest dataset in an empty database.')
    parser.parse_args()
    try:
        report = install()
    except DatasetError as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
