"""kcidb-query command-line executable"""

import argparse
import json
import sys
from google.cloud import bigquery
from kcidb import io_schema


def main():
    """Run the executable"""
    description = 'kcidb-query - Query test results from kernelci.org database'
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        '-d', '--dataset',
        help='Dataset name',
        required=True
    )
    args = parser.parse_args()

    client = bigquery.Client()
    data = dict(version="1")
    for obj_name in ("revision", "build", "test"):
        query_job = client.query("SELECT * FROM `" +
                                 args.dataset + "." + obj_name + "s` ")
        obj_list = [
            dict(item for item in row.items()
                 if item[0] != "id" and item[1] is not None)
            for row in query_job
        ]
        data[obj_name + "_list"] = obj_list
    io_schema.validate(data)
    json.dump(data, sys.stdout, indent=4, sort_keys=True)
